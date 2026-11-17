"""
library.py
Core business logic for the Library Management System:
adding/removing books & members, issuing/returning loans,
searching, and fine calculation.
"""

from datetime import datetime, timedelta
import sqlite3

from .database import Database
from .models import Book, Member, Loan

LOAN_PERIOD_DAYS = 14
FINE_PER_DAY = 5.0  # currency units per day overdue


class LibraryError(Exception):
    """Base exception for library-related errors."""
    pass


class BookNotFoundError(LibraryError):
    pass


class MemberNotFoundError(LibraryError):
    pass


class NoAvailableCopyError(LibraryError):
    pass


class DuplicateISBNError(LibraryError):
    pass


class Library:
    def __init__(self, db_path="data/library.db"):
        self.db = Database(db_path)
        self.conn = self.db.conn

    # ------------------------------------------------------------------
    # Book management
    # ------------------------------------------------------------------
    def add_book(self, title, author, isbn, category="General", copies=1):
        cursor = self.conn.cursor()
        # FIX: pre-check for a duplicate ISBN and raise a clean,
        # catchable DuplicateISBNError instead of letting a raw
        # sqlite3.IntegrityError leak out to the caller.
        cursor.execute("SELECT 1 FROM books WHERE isbn = ?", (isbn,))
        if cursor.fetchone():
            raise DuplicateISBNError(f"A book with ISBN {isbn} already exists")

        cursor.execute(
            "INSERT INTO books (title, author, isbn, category, "
            "total_copies, available_copies) VALUES (?, ?, ?, ?, ?, ?)",
            (title, author, isbn, category, copies, copies)
        )
        self.conn.commit()
        return cursor.lastrowid

    def remove_book(self, book_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM books WHERE book_id = ?", (book_id,))
        book = cursor.fetchone()
        if not book:
            raise BookNotFoundError(f"No book with id {book_id}")
        cursor.execute("DELETE FROM books WHERE book_id = ?", (book_id,))
        self.conn.commit()

    def search_books(self, keyword):
        cursor = self.conn.cursor()
        # FIX: wrap the keyword in % wildcards so LIKE does a substring
        # search. SQLite's LIKE is case-insensitive for ASCII by default,
        # so "pragmatic" now correctly matches "The Pragmatic Programmer".
        pattern = f"%{keyword}%"
        cursor.execute(
            "SELECT * FROM books WHERE title LIKE ? OR author LIKE ?",
            (pattern, pattern)
        )
        rows = cursor.fetchall()
        return [self._row_to_book(r) for r in rows]

    def list_books(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM books ORDER BY title")
        return [self._row_to_book(r) for r in cursor.fetchall()]

    def get_book(self, book_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM books WHERE book_id = ?", (book_id,))
        row = cursor.fetchone()
        if not row:
            raise BookNotFoundError(f"No book with id {book_id}")
        return self._row_to_book(row)

    # ------------------------------------------------------------------
    # Member management
    # ------------------------------------------------------------------
    def add_member(self, name, email, phone=""):
        cursor = self.conn.cursor()
        join_date = datetime.now().strftime("%Y-%m-%d")
        cursor.execute(
            "INSERT INTO members (name, email, phone, join_date) "
            "VALUES (?, ?, ?, ?)",
            (name, email, phone, join_date)
        )
        self.conn.commit()
        return cursor.lastrowid

    def remove_member(self, member_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM members WHERE member_id = ?", (member_id,))
        member = cursor.fetchone()
        if not member:
            raise MemberNotFoundError(f"No member with id {member_id}")
        cursor.execute("DELETE FROM members WHERE member_id = ?", (member_id,))
        self.conn.commit()

    def get_member(self, member_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM members WHERE member_id = ?", (member_id,))
        row = cursor.fetchone()
        if not row:
            raise MemberNotFoundError(f"No member with id {member_id}")
        return self._row_to_member(row)

    def list_members(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM members ORDER BY name")
        return [self._row_to_member(r) for r in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Loan management (issue / return books)
    # ------------------------------------------------------------------
    def issue_book(self, book_id, member_id):
        cursor = self.conn.cursor()

        book = self.get_book(book_id)          # raises BookNotFoundError
        self.get_member(member_id)              # raises MemberNotFoundError

        if book.available_copies < 1:
            raise NoAvailableCopyError(
                f"No available copies of '{book.title}'"
            )

        # FIX: block a member from taking out a second, simultaneous
        # active loan on the same book.
        cursor.execute(
            "SELECT 1 FROM loans WHERE book_id = ? AND member_id = ? "
            "AND return_date IS NULL",
            (book_id, member_id)
        )
        if cursor.fetchone():
            raise LibraryError(
                f"Member {member_id} already has an active loan for "
                f"'{book.title}'"
            )

        issue_date = datetime.now()
        due_date = issue_date + timedelta(days=LOAN_PERIOD_DAYS)

        cursor.execute(
            "INSERT INTO loans (book_id, member_id, issue_date, due_date, "
            "return_date, fine_paid) VALUES (?, ?, ?, ?, NULL, 0)",
            (book_id, member_id,
             issue_date.strftime("%Y-%m-%d"),
             due_date.strftime("%Y-%m-%d"))
        )
        cursor.execute(
            "UPDATE books SET available_copies = available_copies - 1 "
            "WHERE book_id = ?", (book_id,)
        )
        self.conn.commit()
        return cursor.lastrowid

    def return_book(self, loan_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM loans WHERE loan_id = ?", (loan_id,))
        loan = cursor.fetchone()
        if not loan:
            raise LibraryError(f"No loan with id {loan_id}")

        # FIX: reject a loan that's already been returned. Without this,
        # calling return_book() twice on the same loan would increment
        # available_copies twice, letting it exceed total_copies.
        if loan["return_date"] is not None:
            raise LibraryError(f"Loan {loan_id} was already returned")

        return_date = datetime.now()
        due_date = datetime.strptime(loan["due_date"], "%Y-%m-%d")

        # FIX: a book returned exactly on its due date should have zero
        # days late, not be charged a fine. (days_late is naturally 0 in
        # that case since we use plain subtraction, not >=.)
        days_late = (return_date.date() - due_date.date()).days
        fine = max(0, days_late) * FINE_PER_DAY

        cursor.execute(
            "UPDATE loans SET return_date = ?, fine_paid = ? "
            "WHERE loan_id = ?",
            (return_date.strftime("%Y-%m-%d"), fine, loan_id)
        )
        cursor.execute(
            "UPDATE books SET available_copies = available_copies + 1 "
            "WHERE book_id = ?", (loan["book_id"],)
        )
        self.conn.commit()
        return fine

    def list_active_loans(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM loans WHERE return_date IS NULL")
        return [self._row_to_loan(r) for r in cursor.fetchall()]

    def list_overdue_loans(self):
        cursor = self.conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        cursor.execute(
            "SELECT * FROM loans WHERE return_date IS NULL AND due_date < ?",
            (today,)
        )
        return [self._row_to_loan(r) for r in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Row -> dataclass helpers
    # ------------------------------------------------------------------
    def _row_to_book(self, row):
        return Book(
            book_id=row["book_id"], title=row["title"], author=row["author"],
            isbn=row["isbn"], category=row["category"],
            total_copies=row["total_copies"],
            available_copies=row["available_copies"]
        )

    def _row_to_member(self, row):
        return Member(
            member_id=row["member_id"], name=row["name"], email=row["email"],
            phone=row["phone"], join_date=row["join_date"]
        )

    def _row_to_loan(self, row):
        return Loan(
            loan_id=row["loan_id"], book_id=row["book_id"],
            member_id=row["member_id"], issue_date=row["issue_date"],
            due_date=row["due_date"], return_date=row["return_date"],
            fine_paid=row["fine_paid"]
        )

    def close(self):
        self.db.close()
