from typing import List
from fastapi import status, HTTPException, Response, Depends, APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from config.database import get_db
from sqlalchemy import update, or_, func
from controller.bookController import get_book_byISBN, update_book
from datetime import date, timedelta
from utils import get_current_user
from schemas import bookIssue
from schemas.book import updateBook
import model


router = APIRouter(
    prefix= "/issues",
    tags=['IssueBooks']
)


@router.get("/", response_model= List[bookIssue.baseBookIssue])
async def get_issues(db: AsyncSession = Depends(get_db), client : int = Depends(get_current_user)):
    result = await db.execute(select(model.Issue))
    issues = result.scalars().all()
    return issues


@router.get("/search")
async def get_issues(student_id: str, book_id: str, db: AsyncSession = Depends(get_db), client: int = Depends(get_current_user)):
    query = select(model.Issue).where(
        model.Issue.student_id == student_id,
        model.Issue.book_id == book_id
    )
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_issue(issue: bookIssue.createBookIssue, db: AsyncSession = Depends(get_db), client: dict = Depends(get_current_user)):
    query = select(model.Issue).where(
        model.Issue.book_id == issue.book_id,
        model.Issue.student_id == issue.student_id,
        or_(model.Issue.status == "Issued", model.Issue.status == "Renewed")
    )
    result = await db.execute(query)
    issue_exists = result.scalars().first()
    if issue_exists:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Book already issued to the student")

    count_query = select(func.count()).where(
        model.Issue.student_id == issue.student_id,
        or_(model.Issue.status == "Issued", model.Issue.status == "Renewed")
    )
    count_result = await db.execute(count_query)
    issued_books_count = count_result.scalar()
    if issued_books_count >= 10:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Student has already issued 10 books")

    check_status_query = select(model.Student.issue_status).where(model.Student.studentId == issue.student_id)
    result = await db.execute(check_status_query)
    issue_status = result.scalar()

    if issue_status is False:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Student has been blocked")

    new_issue = model.Issue(
        book_id=issue.book_id,
        student_id=issue.student_id,
        user_id=client.jobId
    )

    db.add(new_issue)
    await db.commit()
    await db.refresh(new_issue)

    book = await get_book_byISBN(issue.book_id, db, client)
    print(book)
    res = await update_book(issue.book_id, updateBook(
        edition=book.edition,
        publication=book.publication,
        quantity=book.quantity,
        price=book.price,
        rack_no=book.rack_no,
        available=book.available - 1
    ), db, client)
    print(res)

    return {"message": "Book Issued Successfully"}



@router.put("/{id}", status_code=status.HTTP_202_ACCEPTED)
async def update_issue(id : int, issue : bookIssue.updateBookIssue, db: AsyncSession = Depends(get_db), client : dict = Depends(get_current_user)):
    query = select(model.Issue).where(model.Issue.id == id)
    result = await db.execute(query)
    issue_exists = result.scalars().first()
            
    if not issue_exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
    if issue_exists.status.value == bookIssue.IssueStatus.RETURNED.value: 
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Book has already been returned")
    
    check_status_query = select(model.Student.issue_status).where(model.Student.studentId == issue.student_id)
    result = await db.execute(check_status_query)
    status = result.scalar()
    if status is False:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Student has been blocked")
    
    update_values = {"status": issue.status, "user_id": client.jobId}
    
    if issue.status == "Returned":
        update_values["return_date"] = date.today() 
        book = await get_book_byISBN(issue_exists.book_id, db, client)
        await update_book(issue_exists.book_id, updateBook(edition=book.edition, publication=book.publication, quantity=book.quantity,
        price=book.price, rack_no=book.rack_no, available=book.available + 1), db, client)
        
    elif issue.status == "Renewed":
        if int(issue_exists.renewal_count) == 3:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MAX_RENEWAL count achived")
        update_values["renewal_count"] = issue_exists.renewal_count + 1 
        update_values["due_date"] = issue_exists.due_date + timedelta(days=30) 

    update_query = update(model.Issue).where(model.Issue.id == id).values(update_values)
    await db.execute(update_query)
    await db.commit()
    
    return {"message": "Issue updated successfully"}

