"""
models.py
Simple data classes representing entities in the system.
These are used mainly to structure data returned to the caller;
the actual persistence logic lives in library.py.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Book:
    book_id: Optional[int]
    title: str
    author: str
    isbn: str
    category: str
    total_copies: int
    available_copies: int

    def __str__(self):
        return (f"[{self.book_id}] '{self.title}' by {self.author} "
                f"(ISBN: {self.isbn}) - {self.available_copies}/"
                f"{self.total_copies} available")


@dataclass
class Member:
    member_id: Optional[int]
    name: str
    email: str
    phone: str
    join_date: str

    def __str__(self):
        return f"[{self.member_id}] {self.name} <{self.email}>"


@dataclass
class Loan:
    loan_id: Optional[int]
    book_id: int
    member_id: int
    issue_date: str
    due_date: str
    return_date: Optional[str]
    fine_paid: float

    def __str__(self):
        status = "Returned" if self.return_date else "Active"
        return (f"[{self.loan_id}] Book:{self.book_id} Member:{self.member_id} "
                f"Due:{self.due_date} Status:{status}")
