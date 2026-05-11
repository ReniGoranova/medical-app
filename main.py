from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import mysql.connector

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")


import os


def get_db():
    return mysql.connector.connect(
        host=os.getenv("MYSQLHOST"),
        user=os.getenv("MYSQLUSER"),
        password=os.getenv("MYSQLPASSWORD"),
        database=os.getenv("MYSQLDATABASE"),
        port=int(os.getenv("MYSQLPORT"))
    )


class RegisterData(BaseModel):
    first_name: str
    last_name: str
    email: str
    phone: str
    city: str
    birth_date: str
    gender: str
    username: str
    password: str


class LoginData(BaseModel):
    username: str
    password: str


@app.get("/", response_class=HTMLResponse)
def home():
    with open("templates/index.html", encoding="utf-8") as f:
        return f.read()


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    with open("templates/dashboard.html", encoding="utf-8") as f:
        return f.read()
    
@app.get("/search", response_class=HTMLResponse)
def search():
    with open("templates/search.html", encoding="utf-8") as f:
        return f.read()


@app.get("/doctors")
def get_doctors():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM doctors")
    doctors = cursor.fetchall()

    cursor.close()
    db.close()

    return doctors


@app.post("/register")
def register(data: RegisterData):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM users WHERE username = %s",
        (data.username,)
    )

    existing_user = cursor.fetchone()

    if existing_user:
        cursor.close()
        db.close()
        return {"message": "Потребителят вече съществува"}

    cursor.execute(
    """
    INSERT INTO users
    (first_name, last_name, email, phone, city, birth_date, gender, username, password)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """,
    (
        data.first_name,
        data.last_name,
        data.email,
        data.phone,
        data.city,
        data.birth_date,
        data.gender,
        data.username,
        data.password
    )
)

    db.commit()

    cursor.close()
    db.close()

    return {"message": "Успешна регистрация"}


@app.post("/login")
def login(data: LoginData):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM users WHERE username = %s AND password = %s",
        (data.username, data.password)
    )

    user = cursor.fetchone()

    cursor.close()
    db.close()

    if user:
        return {
            "success": True,
            "message": "Успешен вход"
        }

    return {
        "success": False,
        "message": "Грешно потребителско име или парола"
    }


@app.post("/appointments")
def book_appointment(user: str, doctor_id: int, time: str, reason: str = ""):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM users WHERE username = %s", (user,))
    existing_user = cursor.fetchone()

    if existing_user:
        user_id = existing_user["id"]
    else:
        cursor.execute(
            "INSERT INTO users (username, password) VALUES (%s, %s)",
            (user, "")
        )
        db.commit()
        user_id = cursor.lastrowid

    cursor.execute(
        "SELECT * FROM appointments WHERE doctor_id = %s AND time = %s",
        (doctor_id, time)
    )
    existing = cursor.fetchone()

    if existing:
        cursor.close()
        db.close()
        return {"message": "Този час вече е зает"}

    cursor.execute(
        "INSERT INTO appointments (user_id, doctor_id, time, reason) VALUES (%s, %s, %s, %s)",
        (user_id, doctor_id, time, reason)
    )

    db.commit()

    cursor.close()
    db.close()

    return {"message": "Часът е записан успешно"}

@app.get("/appointments")
def get_appointments():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT appointments.id, users.username, doctors.name, appointments.time
        FROM appointments
        JOIN users ON appointments.user_id = users.id
        JOIN doctors ON appointments.doctor_id = doctors.id
    """)

    appointments = cursor.fetchall()

    cursor.close()
    db.close()

    return appointments


@app.delete("/appointments/{appointment_id}")
def delete_appointment(appointment_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("DELETE FROM appointments WHERE id = %s", (appointment_id,))
    db.commit()

    cursor.close()
    db.close()

    return {"message": "Часът е изтрит успешно"}

@app.get("/busy-times")
def get_busy_times(doctor_id: int, date: str):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        "SELECT time FROM appointments WHERE doctor_id = %s AND time LIKE %s",
        (doctor_id, date + "%")
    )

    results = cursor.fetchall()

    cursor.close()
    db.close()

    busy_times = []

    for row in results:
        full_time = row["time"]
        only_time = full_time.split(" ")[1]
        busy_times.append(only_time)

    return busy_times

@app.get("/doctor/{doctor_id}", response_class=HTMLResponse)
def doctor_profile(doctor_id: int):
    with open("templates/doctor_profile.html", encoding="utf-8") as f:
        return f.read()
    
@app.get("/doctor-data/{doctor_id}")
def doctor_data(doctor_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM doctors WHERE id = %s",
        (doctor_id,)
    )

    doctor = cursor.fetchone()

    cursor.close()
    db.close()

    return doctor

from pydantic import BaseModel

class ReviewData(BaseModel):
    username: str
    doctor_id: int
    rating: int
    comment: str


@app.post("/reviews")
def add_review(data: ReviewData):

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM users WHERE username = %s",
        (data.username,)
    )

    user = cursor.fetchone()

    if not user:
        cursor.close()
        db.close()
        return {"message": "Потребителят не е намерен"}

    cursor.execute(
        """
        INSERT INTO reviews
        (user_id, doctor_id, rating, comment)
        VALUES (%s, %s, %s, %s)
        """,
        (
            user["id"],
            data.doctor_id,
            data.rating,
            data.comment
        )
    )

    db.commit()

    cursor.close()
    db.close()

    return {"message": "Отзивът е добавен успешно"}

@app.get("/reviews/{doctor_id}")
def get_reviews(doctor_id: int):

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT reviews.*, users.username
        FROM reviews
        JOIN users ON reviews.user_id = users.id
        WHERE doctor_id = %s
        ORDER BY created_at DESC
        """,
        (doctor_id,)
    )

    reviews = cursor.fetchall()

    cursor.close()
    db.close()

    return reviews

@app.get("/register-page", response_class=HTMLResponse)
def register_page():
    with open("templates/register.html", encoding="utf-8") as f:
        return f.read()

@app.get("/my-appointments", response_class=HTMLResponse)
def my_appointments_page():
    with open("templates/my_appointments.html", encoding="utf-8") as f:
        return f.read()


@app.get("/my-appointments-data")
def my_appointments_data(username: str):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT
            appointments.id,
            appointments.time,
            appointments.reason,
            doctors.name AS doctor_name,
            doctors.specialty,
            doctors.city,
            doctors.address,
            doctors.phone
        FROM appointments
        JOIN users ON appointments.user_id = users.id
        JOIN doctors ON appointments.doctor_id = doctors.id
        WHERE users.username = %s
        ORDER BY appointments.time ASC
        """,
        (username,)
    )

    appointments = cursor.fetchall()

    cursor.close()
    db.close()

    return appointments

@app.get("/booking-details", response_class=HTMLResponse)
def booking_details_page():
    with open("templates/booking_details.html", encoding="utf-8") as f:
        return f.read()
    
@app.get("/my-profile", response_class=HTMLResponse)
def my_profile_page():
    with open("templates/my_profile.html", encoding="utf-8") as f:
        return f.read() 
    
class ProfileUpdateData(BaseModel):
    username: str
    email: str
    phone: str


@app.get("/profile-data/{username}")
def profile_data(username: str):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT
            id,
            first_name,
            last_name,
            email,
            phone,
            city,
            birth_date,
            gender,
            username
        FROM users
        WHERE username = %s
        """,
        (username,)
    )

    user = cursor.fetchone()

    cursor.close()
    db.close()

    return user


@app.put("/profile-update")
def update_profile(data: ProfileUpdateData):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        """
        UPDATE users
        SET email = %s, phone = %s
        WHERE username = %s
        """,
        (data.email, data.phone, data.username)
    )

    db.commit()

    cursor.close()
    db.close()

    return {"message": "Профилът е обновен успешно"}

@app.get("/patient-details", response_class=HTMLResponse)
def patient_details_page():
    with open("templates/patient_details.html", encoding="utf-8") as f:
        return f.read()


