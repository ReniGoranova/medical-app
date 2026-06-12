from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import mysql.connector
import os
from datetime import datetime, date, timedelta


app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")


ALL_APPOINTMENT_TIMES = [
    "09:00", "09:30", "10:00", "10:30",
    "11:00", "11:30", "12:00", "12:30",
    "13:00", "13:30", "14:00", "14:30",
    "15:00", "15:30", "16:00", "16:30",
    "17:00", "17:30", "18:00"
]


def get_db():
    return mysql.connector.connect(
        host=os.getenv("MYSQLHOST", "localhost"),
        user=os.getenv("MYSQLUSER", "medical_user"),
        password=os.getenv("MYSQLPASSWORD", "medical123"),
        database="medical_app",
        port=int(os.getenv("MYSQLPORT", "3306"))
    )


def ensure_appointment_extra_columns(cursor):
    """Добавя липсващи колони към appointments за плащане и бележки.
    Така кодът работи и ако таблицата вече е създадена по стария вариант.
    """
    cursor.execute("SHOW COLUMNS FROM appointments")
    existing_columns = {row["Field"] for row in cursor.fetchall()}

    columns_to_add = {
        "payment_method": "VARCHAR(100) NULL",
        "appointment_patient_name": "VARCHAR(150) NULL",
        "appointment_patient_phone": "VARCHAR(40) NULL",
        "appointment_note": "TEXT NULL"
    }

    for column_name, column_definition in columns_to_add.items():
        if column_name not in existing_columns:
            cursor.execute(
                f"ALTER TABLE appointments ADD COLUMN {column_name} {column_definition}"
            )


def ensure_doctor_day_offs_table(cursor):
    """Създава таблица за дните, в които лекарят няма да приема пациенти."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS doctor_day_offs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            doctor_id INT NOT NULL,
            off_date DATE NOT NULL,
            reason VARCHAR(255) NOT NULL,
            note TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_doctor_day_off (doctor_id, off_date),
            CONSTRAINT fk_day_offs_doctor
                FOREIGN KEY (doctor_id) REFERENCES doctors(id)
                ON DELETE CASCADE
                ON UPDATE CASCADE
        )
        """
    )


def is_doctor_day_off(cursor, doctor_id: int, selected_date: str) -> bool:
    ensure_doctor_day_offs_table(cursor)
    cursor.execute(
        """
        SELECT id
        FROM doctor_day_offs
        WHERE doctor_id = %s AND off_date = %s
        LIMIT 1
        """,
        (doctor_id, selected_date)
    )
    return cursor.fetchone() is not None


EXTRA_NON_WORKING_DAYS = {
    date(2026, 1, 2),  
}


def orthodox_easter_date(year: int) -> date:
    """Връща датата на православния Великден по григорианския календар."""
    a = year % 4
    b = year % 7
    c = year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = ((d + e + 114) % 31) + 1

    julian_easter = date(year, month, day)
    return julian_easter + timedelta(days=13)


def next_working_day_after(day_value: date, used_days: set[date]) -> date:
    next_day = day_value + timedelta(days=1)

    while next_day.weekday() >= 5 or next_day in used_days:
        next_day += timedelta(days=1)

    return next_day


def get_bulgarian_non_working_days(year: int) -> set[date]:
    """Официални празници в България + заместващи почивни дни, когато празникът е през уикенда."""
    fixed_holidays = [
        date(year, 1, 1),
        date(year, 3, 3),
        date(year, 5, 1),
        date(year, 5, 6),
        date(year, 5, 24),
        date(year, 9, 6),
        date(year, 9, 22),
        date(year, 12, 24),
        date(year, 12, 25),
        date(year, 12, 26),
    ]

    easter = orthodox_easter_date(year)
    easter_holidays = [
        easter - timedelta(days=2),
        easter - timedelta(days=1),
        easter,
        easter + timedelta(days=1),
    ]

    non_working_days = set(fixed_holidays + easter_holidays)

    for holiday in fixed_holidays:
        if holiday.weekday() >= 5:
            substitute_day = next_working_day_after(holiday, non_working_days)
            non_working_days.add(substitute_day)

    non_working_days.update(EXTRA_NON_WORKING_DAYS)

    return non_working_days


def parse_appointment_datetime(value: str) -> datetime:
    cleaned_value = str(value).replace("T", " ").strip()

    for date_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(cleaned_value, date_format)
        except ValueError:
            pass

    raise ValueError("Невалиден формат на дата и час.")


def is_non_working_day(day_value: date) -> bool:
    return day_value.weekday() >= 5 or day_value in get_bulgarian_non_working_days(day_value.year)


def validate_working_day(value: str):
    appointment_datetime = parse_appointment_datetime(value)

    if is_non_working_day(appointment_datetime.date()):
        return False, "Избраната дата е официален почивен ден, събота или неделя. Моля, изберете работен ден."

    return True, ""



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


class DoctorLoginData(BaseModel):
    doctor_username: str
    doctor_password: str


class ReviewData(BaseModel):
    username: str
    doctor_id: int
    rating: int
    comment: str


class ProfileUpdateData(BaseModel):
    username: str
    first_name: str
    last_name: str
    email: str
    phone: str
    city: str


class DoctorRegisterData(BaseModel):
    doctor_username: str
    doctor_password: str
    name: str
    specialty: str
    city: str
    address: str
    phone: str
    email: str
    experience: str
    description: str
    education: str
    qualifications: str
    biography: str


class DoctorUpdateData(BaseModel):
    doctor_id: int
    name: str
    specialty: str
    city: str
    address: str
    phone: str
    email: str
    experience: str
    description: str
    education: str
    qualifications: str
    biography: str


class BlockTimeData(BaseModel):
    doctor_id: int
    time: str
    reason: str = "Резервиран по телефон"
    patient_name: str = ""
    patient_phone: str = ""
    payment_method: str = ""
    note: str = ""


class DoctorCancelData(BaseModel):
    appointment_id: int
    reason: str
    lock_time: bool = False


class DoctorDayOffData(BaseModel):
    doctor_id: int
    off_date: str
    reason: str
    note: str = ""


class PatientCancelData(BaseModel):
    appointment_id: int
    reason: str = "Отказан от пациент"


@app.get("/", response_class=HTMLResponse)
def home():
    with open("templates/index.html", encoding="utf-8") as f:
        return f.read()


@app.get("/search", response_class=HTMLResponse)
def search():
    with open("templates/search.html", encoding="utf-8") as f:
        return f.read()


@app.get("/about-medical", response_class=HTMLResponse)
def about_medical_page():
    with open("templates/about_medical.html", encoding="utf-8") as f:
        return f.read()


@app.get("/for-doctors", response_class=HTMLResponse)
def for_doctors_page():
    with open("templates/for_doctors.html", encoding="utf-8") as f:
        return f.read()


@app.get("/register-page", response_class=HTMLResponse)
def register_page():
    with open("templates/register.html", encoding="utf-8") as f:
        return f.read()


@app.get("/doctor-register", response_class=HTMLResponse)
def doctor_register_page():
    with open("templates/doctor_register.html", encoding="utf-8") as f:
        return f.read()


@app.get("/doctor-dashboard", response_class=HTMLResponse)
def doctor_dashboard_page():
    with open("templates/doctor_dashboard.html", encoding="utf-8") as f:
        return f.read()


@app.get("/doctor/{doctor_id}", response_class=HTMLResponse)
def doctor_profile(doctor_id: int):
    with open("templates/doctor_profile.html", encoding="utf-8") as f:
        return f.read()


@app.get("/my-appointments", response_class=HTMLResponse)
def my_appointments_page():
    with open("templates/my_appointments.html", encoding="utf-8") as f:
        return f.read()


@app.get("/booking-details", response_class=HTMLResponse)
def booking_details_page():
    with open("templates/booking_details.html", encoding="utf-8") as f:
        return f.read()


@app.get("/my-profile", response_class=HTMLResponse)
def my_profile_page():
    with open("templates/my_profile.html", encoding="utf-8") as f:
        return f.read()


@app.get("/my-cancellations-page", response_class=HTMLResponse)
def my_cancellations_page():
    with open("templates/my_cancellations.html", encoding="utf-8") as f:
        return f.read()


@app.get("/patient-details", response_class=HTMLResponse)
def patient_details_page():
    with open("templates/patient_details.html", encoding="utf-8") as f:
        return f.read()


@app.post("/register")
def register(data: RegisterData):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        "SELECT id FROM users WHERE username = %s",
        (data.username,)
    )
    if cursor.fetchone():
        cursor.close()
        db.close()
        return {"message": "Потребителят вече съществува"}

    cursor.execute(
        "SELECT id FROM users WHERE email = %s",
        (data.email,)
    )
    if cursor.fetchone():
        cursor.close()
        db.close()
        return {"message": "Този имейл вече се използва от друг профил."}

    cursor.execute(
        "SELECT id FROM doctors WHERE email = %s",
        (data.email,)
    )
    if cursor.fetchone():
        cursor.close()
        db.close()
        return {"message": "Този имейл вече се използва от лекарски профил."}

    cursor.execute(
        "SELECT id FROM users WHERE phone = %s",
        (data.phone,)
    )
    if cursor.fetchone():
        cursor.close()
        db.close()
        return {"message": "Този телефон вече се използва от друг профил."}

    cursor.execute(
        "SELECT id FROM doctors WHERE phone = %s",
        (data.phone,)
    )
    if cursor.fetchone():
        cursor.close()
        db.close()
        return {"message": "Този телефон вече се използва от лекарски профил."}

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


@app.post("/doctor-login")
def doctor_login(data: DoctorLoginData):
    db = None
    cursor = None

    try:
        entered_username = data.doctor_username.strip()
        entered_password = str(data.doctor_password).strip()

        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute("SELECT DATABASE() AS current_database")
        database_info = cursor.fetchone()
        current_database = database_info["current_database"]

        cursor.execute(
            """
            SELECT
                id,
                name,
                specialty,
                city,
                doctor_username,
                CAST(doctor_password AS CHAR) AS doctor_password
            FROM doctors
            """
        )

        doctors = cursor.fetchall()

        def clean_value(value):
            if value is None:
                return ""

            return (
                str(value)
                .replace("\\u00a0", "")
                .replace("\\ufeff", "")
                .strip()
                .lower()
            )

        entered_username_clean = clean_value(entered_username)
        entered_password_clean = clean_value(entered_password)

        for doctor in doctors:
            db_username_clean = clean_value(doctor.get("doctor_username"))
            db_password_clean = clean_value(doctor.get("doctor_password"))

            if db_username_clean == entered_username_clean:
                if db_password_clean == entered_password_clean:
                    return {
                        "success": True,
                        "message": "Успешен вход като лекар",
                        "doctor_id": doctor["id"],
                        "doctor_name": doctor["name"],
                        "doctor_username": doctor["doctor_username"],
                        "specialty": doctor["specialty"],
                        "city": doctor["city"]
                    }

                return {
                    "success": False,
                    "message": "Грешна парола за този лекар"
                }

        available_usernames = []

        for doctor in doctors:
            if doctor.get("doctor_username"):
                available_usernames.append(str(doctor.get("doctor_username")))

        return {
            "success": False,
            "message": (
                "Не е намерен лекар с това потребителско име. "
                f"Проверена база: {current_database}. "
                f"Налични лекарски потребителски имена: {', '.join(available_usernames) if available_usernames else 'няма'}"
            )
        }

    except mysql.connector.Error as error:
        return {
            "success": False,
            "message": f"Грешка в базата данни: {error}"
        }

    finally:
        if cursor:
            cursor.close()

        if db:
            db.close()



@app.post("/doctor-register-submit")
def doctor_register_submit(data: DoctorRegisterData):
    """Регистрира нов лекар в таблица doctors."""
    db = None
    cursor = None

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            "SELECT id FROM doctors WHERE doctor_username = %s",
            (data.doctor_username,)
        )
        if cursor.fetchone():
            return {
                "success": False,
                "message": "Лекар с това потребителско име вече съществува."
            }

        cursor.execute(
            "SELECT id FROM doctors WHERE email = %s",
            (data.email,)
        )
        if cursor.fetchone():
            return {
                "success": False,
                "message": "Този имейл вече се използва от друг лекар."
            }

        cursor.execute(
            "SELECT id FROM users WHERE email = %s",
            (data.email,)
        )
        if cursor.fetchone():
            return {
                "success": False,
                "message": "Този имейл вече се използва от пациентски профил."
            }


        cursor.execute(
            "SELECT id FROM doctors WHERE phone = %s",
            (data.phone,)
        )
        if cursor.fetchone():
            return {
                "success": False,
                "message": "Този телефон вече се използва от друг лекар."
            }

        cursor.execute(
            "SELECT id FROM users WHERE phone = %s",
            (data.phone,)
        )
        if cursor.fetchone():
            return {
                "success": False,
                "message": "Този телефон вече се използва от пациентски профил."
            }

        cursor.execute(
            """
            INSERT INTO doctors
            (name, specialty, city, address, phone, email, experience,
             description, education, qualifications, biography,
             doctor_username, doctor_password)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                data.name,
                data.specialty,
                data.city,
                data.address,
                data.phone,
                data.email,
                data.experience,
                data.description,
                data.education,
                data.qualifications,
                data.biography,
                data.doctor_username,
                data.doctor_password
            )
        )

        db.commit()

        new_id = cursor.lastrowid

        return {
            "success": True,
            "message": "Регистрацията е успешна!",
            "doctor_id": new_id,
            "doctor_name": data.name,
            "doctor_username": data.doctor_username
        }

    except mysql.connector.Error as error:
        if db:
            db.rollback()
        return {
            "success": False,
            "message": f"Грешка в базата данни: {error}"
        }

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


@app.get("/doctor-data/{doctor_id}")
def doctor_data(doctor_id: int):
    """Връща пълните данни за лекар (за пациентския профил и за лекарския dashboard)."""
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM doctors WHERE id = %s",
        (doctor_id,)
    )

    doctor = cursor.fetchone()

    cursor.close()
    db.close()

    if doctor and "doctor_password" in doctor:
        doctor["doctor_password"] = None

    return doctor


@app.put("/doctor-update")
def doctor_update(data: DoctorUpdateData):
    """Обновява лекарския профил."""
    db = None
    cursor = None

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            "SELECT id FROM doctors WHERE email = %s AND id != %s",
            (data.email, data.doctor_id)
        )
        if cursor.fetchone():
            return {
                "success": False,
                "message": "Този имейл вече се използва от друг лекар."
            }

        cursor.execute(
            "SELECT id FROM users WHERE email = %s",
            (data.email,)
        )
        if cursor.fetchone():
            return {
                "success": False,
                "message": "Този имейл вече се използва от пациентски профил."
            }

        cursor.execute(
            "SELECT id FROM doctors WHERE phone = %s AND id != %s",
            (data.phone, data.doctor_id)
        )
        if cursor.fetchone():
            return {
                "success": False,
                "message": "Този телефон вече се използва от друг лекар."
            }

        cursor.execute(
            "SELECT id FROM users WHERE phone = %s",
            (data.phone,)
        )
        if cursor.fetchone():
            return {
                "success": False,
                "message": "Този телефон вече се използва от пациентски профил."
            }

        cursor.execute(
            """
            UPDATE doctors
            SET
                name = %s,
                specialty = %s,
                city = %s,
                address = %s,
                phone = %s,
                email = %s,
                experience = %s,
                description = %s,
                education = %s,
                qualifications = %s,
                biography = %s
            WHERE id = %s
            """,
            (
                data.name,
                data.specialty,
                data.city,
                data.address,
                data.phone,
                data.email,
                data.experience,
                data.description,
                data.education,
                data.qualifications,
                data.biography,
                data.doctor_id
            )
        )

        db.commit()

        if cursor.rowcount == 0:
            return {
                "success": False,
                "message": "Лекарят не е намерен."
            }

        return {
            "success": True,
            "message": "Профилът е обновен успешно."
        }

    except mysql.connector.Error as error:
        if db:
            db.rollback()
        return {
            "success": False,
            "message": f"Грешка в базата данни: {error}"
        }

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()



@app.get("/doctor-schedule/{doctor_id}")
def doctor_schedule(doctor_id: int, week_start: str):
    """
    Връща всички часове за един лекар в дадена седмица.
    week_start = YYYY-MM-DD (понеделник на седмицата).
    Връща списък от записи: {id, time, reason, patient_name, patient_phone, is_blocked}.
    """
    db = None
    cursor = None

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        ensure_appointment_extra_columns(cursor)
        db.commit()

        cursor.execute(
            """
            SELECT
                appointments.id,
                appointments.time,
                appointments.reason,
                appointments.payment_method,
                appointments.appointment_patient_name,
                appointments.appointment_patient_phone,
                appointments.appointment_note,
                appointments.user_id,
                users.first_name,
                users.last_name,
                users.phone,
                users.username
            FROM appointments
            LEFT JOIN users ON appointments.user_id = users.id
            WHERE appointments.doctor_id = %s
              AND DATE(appointments.time) >= %s
              AND DATE(appointments.time) < DATE_ADD(%s, INTERVAL 7 DAY)
            ORDER BY appointments.time ASC
            """,
            (doctor_id, week_start, week_start)
        )

        rows = cursor.fetchall()

        result = []
        for row in rows:
            is_blocked = row["user_id"] == 0 or row["user_id"] is None

            stored_patient_name = row.get("appointment_patient_name") or ""
            stored_patient_phone = row.get("appointment_patient_phone") or ""

            if stored_patient_name:
                patient_name = stored_patient_name
            elif not is_blocked:
                first = row.get("first_name") or ""
                last = row.get("last_name") or ""
                patient_name = (first + " " + last).strip()
                if not patient_name:
                    patient_name = row.get("username") or ""
            else:
                patient_name = ""

            if stored_patient_phone:
                patient_phone = stored_patient_phone
            elif not is_blocked:
                patient_phone = row.get("phone") or ""
            else:
                patient_phone = ""

            result.append({
                "id": row["id"],
                "time": str(row["time"]),
                "reason": row.get("reason") or "",
                "payment_method": row.get("payment_method") or "",
                "appointment_note": row.get("appointment_note") or "",
                "is_blocked": is_blocked,
                "patient_name": patient_name,
                "patient_phone": patient_phone
            })

        return result

    except mysql.connector.Error as error:
        return {"error": f"Грешка в базата данни: {error}"}

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()




@app.get("/doctor-day-off-status/{doctor_id}")
def doctor_day_off_status(doctor_id: int, date: str):
    """Проверява дали конкретна дата е маркирана като неработна за лекаря."""
    db = None
    cursor = None

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        ensure_doctor_day_offs_table(cursor)
        db.commit()

        cursor.execute(
            """
            SELECT id, off_date, reason, note
            FROM doctor_day_offs
            WHERE doctor_id = %s AND off_date = %s
            LIMIT 1
            """,
            (doctor_id, date)
        )
        row = cursor.fetchone()

        if not row:
            return {"is_day_off": False}

        return {
            "is_day_off": True,
            "id": row["id"],
            "off_date": str(row["off_date"]),
            "reason": row.get("reason") or "Неработен ден",
            "note": row.get("note") or ""
        }

    except mysql.connector.Error as error:
        return {"is_day_off": False, "error": f"Грешка в базата данни: {error}"}

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


@app.get("/doctor-day-offs/{doctor_id}")
def doctor_day_offs(doctor_id: int, week_start: str):
    """Връща маркираните неработни дни на лекаря за избраната седмица."""
    db = None
    cursor = None

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        ensure_doctor_day_offs_table(cursor)
        db.commit()

        cursor.execute(
            """
            SELECT id, doctor_id, off_date, reason, note, created_at
            FROM doctor_day_offs
            WHERE doctor_id = %s
              AND off_date >= %s
              AND off_date < DATE_ADD(%s, INTERVAL 7 DAY)
            ORDER BY off_date ASC
            """,
            (doctor_id, week_start, week_start)
        )

        rows = cursor.fetchall()
        result = []
        for row in rows:
            result.append({
                "id": row["id"],
                "doctor_id": row["doctor_id"],
                "off_date": str(row["off_date"]),
                "reason": row.get("reason") or "Неработен ден",
                "note": row.get("note") or "",
                "created_at": str(row.get("created_at") or "")
            })

        return result

    except mysql.connector.Error as error:
        return {"error": f"Грешка в базата данни: {error}"}

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()




@app.get("/doctor-day-offs-range/{doctor_id}")
def doctor_day_offs_range(doctor_id: int, start_date: str, end_date: str):
    """Връща всички неработни дни на лекаря в даден период.
    Използва се от пациентския календар, за да не могат тези дати да се избират.
    """
    db = None
    cursor = None

    try:
        datetime.strptime(start_date, "%Y-%m-%d")
        datetime.strptime(end_date, "%Y-%m-%d")

        db = get_db()
        cursor = db.cursor(dictionary=True)
        ensure_doctor_day_offs_table(cursor)
        db.commit()

        cursor.execute(
            """
            SELECT id, off_date, reason, note
            FROM doctor_day_offs
            WHERE doctor_id = %s
              AND off_date >= %s
              AND off_date <= %s
            ORDER BY off_date ASC
            """,
            (doctor_id, start_date, end_date)
        )

        rows = cursor.fetchall()
        result = []

        for row in rows:
            result.append({
                "id": row["id"],
                "off_date": str(row["off_date"]),
                "reason": row.get("reason") or "Неработен ден",
                "note": row.get("note") or ""
            })

        return result

    except ValueError:
        return {"error": "Невалиден формат на дата."}

    except mysql.connector.Error as error:
        return {"error": f"Грешка в базата данни: {error}"}

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()

@app.post("/doctor-mark-day-off")
def doctor_mark_day_off(data: DoctorDayOffData):
    """
    Маркира конкретна дата като неработна за лекаря.
    Всички вече записани пациентски часове за тази дата се записват като отказани,
    след което денят се блокира за нови резервации.
    """
    db = None
    cursor = None

    try:
        selected_day = datetime.strptime(data.off_date, "%Y-%m-%d").date()
    except ValueError:
        return {
            "success": False,
            "message": "Невалиден формат на дата."
        }

    today = date.today()
    if selected_day <= today:
        return {
            "success": False,
            "message": "Неработен ден може да бъде маркиран най-късно до предходния ден. Не можете да маркирате текущия или минал ден като неработен."
        }

    if is_non_working_day(selected_day):
        return {
            "success": False,
            "message": "Тази дата вече е почивен ден, събота или неделя."
        }

    if not data.reason.strip():
        return {
            "success": False,
            "message": "Моля, посочете причина."
        }

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        ensure_appointment_extra_columns(cursor)
        ensure_doctor_day_offs_table(cursor)
        db.commit()

        cursor.execute(
            "SELECT id FROM doctors WHERE id = %s",
            (data.doctor_id,)
        )
        if not cursor.fetchone():
            return {
                "success": False,
                "message": "Лекарят не е намерен."
            }

        cursor.execute(
            """
            SELECT id, user_id, doctor_id, time
            FROM appointments
            WHERE doctor_id = %s AND DATE(time) = %s
            """,
            (data.doctor_id, data.off_date)
        )
        appointments_for_day = cursor.fetchall()

        cancelled_count = 0
        for appointment in appointments_for_day:
            if appointment.get("user_id") is not None and appointment.get("user_id") != 0:
                cursor.execute(
                    """
                    INSERT INTO cancellations
                    (appointment_id, doctor_id, user_id, appointment_time, reason, cancelled_by, seen_by_recipient)
                    VALUES (%s, %s, %s, %s, %s, 'doctor', 0)
                    """,
                    (
                        appointment["id"],
                        appointment["doctor_id"],
                        appointment["user_id"],
                        str(appointment["time"]),
                        data.reason.strip()
                    )
                )
                cancelled_count += 1

        cursor.execute(
            """
            DELETE FROM appointments
            WHERE doctor_id = %s AND DATE(time) = %s
            """,
            (data.doctor_id, data.off_date)
        )

        cursor.execute(
            """
            INSERT INTO doctor_day_offs (doctor_id, off_date, reason, note)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                reason = VALUES(reason),
                note = VALUES(note)
            """,
            (
                data.doctor_id,
                data.off_date,
                data.reason.strip(),
                data.note.strip()
            )
        )

        db.commit()

        return {
            "success": True,
            "message": "Денят е маркиран като неработен.",
            "cancelled_count": cancelled_count
        }

    except mysql.connector.Error as error:
        if db:
            db.rollback()
        return {
            "success": False,
            "message": f"Грешка в базата данни: {error}"
        }

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


@app.delete("/doctor-day-off/{day_off_id}")
def doctor_remove_day_off(day_off_id: int):
    """Премахва маркиран неработен ден и отново позволява резервации за датата."""
    db = None
    cursor = None

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        ensure_doctor_day_offs_table(cursor)
        db.commit()

        cursor.execute(
            "DELETE FROM doctor_day_offs WHERE id = %s",
            (day_off_id,)
        )
        db.commit()

        if cursor.rowcount == 0:
            return {
                "success": False,
                "message": "Неработният ден не е намерен."
            }

        return {
            "success": True,
            "message": "Неработният ден е премахнат."
        }

    except mysql.connector.Error as error:
        if db:
            db.rollback()
        return {
            "success": False,
            "message": f"Грешка в базата данни: {error}"
        }

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


@app.post("/doctor-block-time")
def doctor_block_time(data: BlockTimeData):
    """Лекарят заключва даден час (за да не може пациент да го резервира)."""
    db = None
    cursor = None

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        ensure_appointment_extra_columns(cursor)
        db.commit()

        is_allowed_day, validation_message = validate_working_day(data.time)
        if not is_allowed_day:
            return {
                "success": False,
                "message": validation_message
            }

        selected_date = parse_appointment_datetime(data.time).date().strftime("%Y-%m-%d")
        if is_doctor_day_off(cursor, data.doctor_id, selected_date):
            return {
                "success": False,
                "message": "Този ден е маркиран като неработен и не може да се заключва отделен час."
            }

        cursor.execute(
            """
            SELECT id FROM appointments
            WHERE doctor_id = %s AND time = %s
            """,
            (data.doctor_id, data.time)
        )

        if cursor.fetchone():
            return {
                "success": False,
                "message": "Този час вече е зает или заключен."
            }

        cursor.execute(
            """
            INSERT INTO appointments
            (user_id, doctor_id, time, reason, payment_method,
             appointment_patient_name, appointment_patient_phone, appointment_note)
            VALUES (NULL, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                data.doctor_id,
                data.time,
                data.reason,
                data.payment_method,
                data.patient_name,
                data.patient_phone,
                data.note
            )
        )

        db.commit()

        return {
            "success": True,
            "message": "Часът е заключен."
        }

    except mysql.connector.Error as error:
        if db:
            db.rollback()
        return {
            "success": False,
            "message": f"Грешка в базата данни: {error}"
        }

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


@app.delete("/doctor-appointment/{appointment_id}")
def doctor_delete_appointment(appointment_id: int):
    """Лекарят премахва час (зает или заключен)."""
    db = None
    cursor = None

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            "DELETE FROM appointments WHERE id = %s",
            (appointment_id,)
        )

        db.commit()

        if cursor.rowcount == 0:
            return {
                "success": False,
                "message": "Часът не е намерен."
            }

        return {
            "success": True,
            "message": "Часът е премахнат успешно."
        }

    except mysql.connector.Error as error:
        if db:
            db.rollback()
        return {
            "success": False,
            "message": f"Грешка в базата данни: {error}"
        }

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()



@app.post("/doctor-cancel-appointment")
def doctor_cancel_appointment(data: DoctorCancelData):
    """
    Лекарят отказва запазен пациентски час.
    Ако lock_time=False, часът се освобождава за друг пациент.
    Ако lock_time=True, часът остава заключен и не се вижда като свободен.
    """
    db = None
    cursor = None

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        ensure_appointment_extra_columns(cursor)
        db.commit()

        cursor.execute(
            """
            SELECT id, user_id, doctor_id, time
            FROM appointments
            WHERE id = %s
            """,
            (data.appointment_id,)
        )

        appointment = cursor.fetchone()

        if not appointment:
            return {
                "success": False,
                "message": "Часът не е намерен."
            }

        if appointment["user_id"] == 0 or appointment["user_id"] is None:
            return {
                "success": False,
                "message": "Този час вече е заключен от Вас. Може само да го отключите."
            }


        cursor.execute(
            """
            INSERT INTO cancellations
            (appointment_id, doctor_id, user_id, appointment_time, reason, cancelled_by, seen_by_recipient)
            VALUES (%s, %s, %s, %s, %s, 'doctor', 0)
            """,
            (
                appointment["id"],
                appointment["doctor_id"],
                appointment["user_id"],
                str(appointment["time"]),
                data.reason
            )
        )

        if data.lock_time:
            cursor.execute(
                """
                UPDATE appointments
                SET
                    user_id = NULL,
                    reason = 'Заключен от лекаря',
                    payment_method = NULL,
                    appointment_patient_name = NULL,
                    appointment_patient_phone = NULL,
                    appointment_note = %s
                WHERE id = %s
                """,
                (f"Часът е отказан от лекаря и остава заключен. Причина: {data.reason}", data.appointment_id)
            )
            success_message = "Часът е отказан и остава заключен."
        else:
            cursor.execute(
                "DELETE FROM appointments WHERE id = %s",
                (data.appointment_id,)
            )
            success_message = "Часът е отказан и освободен за друг пациент."

        db.commit()

        return {
            "success": True,
            "message": success_message
        }

    except mysql.connector.Error as error:
        if db:
            db.rollback()
        return {
            "success": False,
            "message": f"Грешка в базата данни: {error}"
        }

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


@app.post("/patient-cancel-appointment")
def patient_cancel_appointment(data: PatientCancelData):
    """
    Пациентът отменя запазен час. Часът се премахва, но се записва
    в cancellations, за да види лекарят отказа в графика си.
    """
    db = None
    cursor = None

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT id, user_id, doctor_id, time
            FROM appointments
            WHERE id = %s
            """,
            (data.appointment_id,)
        )

        appointment = cursor.fetchone()

        if not appointment:
            return {
                "success": False,
                "message": "Часът не е намерен."
            }


        cursor.execute(
            """
            INSERT INTO cancellations
            (doctor_id, user_id, appointment_time, reason, cancelled_by, seen_by_recipient)
            VALUES (%s, %s, %s, %s, 'patient', 0)
            """,
            (
                appointment["doctor_id"],
                appointment["user_id"],
                str(appointment["time"]),
                data.reason or "Отказан от пациент"
            )
        )


        cursor.execute(
            "DELETE FROM appointments WHERE id = %s",
            (data.appointment_id,)
        )

        db.commit()

        return {
            "success": True,
            "message": "Часът е отменен."
        }

    except mysql.connector.Error as error:
        if db:
            db.rollback()
        return {
            "success": False,
            "message": f"Грешка в базата данни: {error}"
        }

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


@app.get("/my-cancellations")
def my_cancellations(username: str):
    """Връща отказите, които пациентът е получил от лекари."""
    db = None
    cursor = None

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                c.id,
                c.appointment_time,
                c.reason,
                c.seen_by_recipient,
                c.created_at,
                d.name AS doctor_name,
                d.specialty,
                d.city,
                d.address,
                d.phone
            FROM cancellations c
            JOIN users u ON c.user_id = u.id
            LEFT JOIN doctors d ON c.doctor_id = d.id
            WHERE u.username = %s
              AND c.cancelled_by = 'doctor'
            ORDER BY c.created_at DESC
            """,
            (username,)
        )

        rows = cursor.fetchall()

        result = []
        for row in rows:
            result.append({
                "id": row["id"],
                "appointment_time": str(row["appointment_time"]),
                "reason": row["reason"],
                "seen": bool(row["seen_by_recipient"]),
                "created_at": str(row["created_at"]),
                "doctor_name": row.get("doctor_name") or "—",
                "specialty": row.get("specialty") or "",
                "city": row.get("city") or "",
                "address": row.get("address") or "",
                "phone": row.get("phone") or ""
            })

        return result

    except mysql.connector.Error as error:
        return {"error": f"Грешка в базата данни: {error}"}

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


@app.post("/dismiss-cancellation/{cancellation_id}")
def dismiss_cancellation(cancellation_id: int):
    """Пациентът отбелязва, че е видял известието за отказ."""
    db = None
    cursor = None

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            "UPDATE cancellations SET seen_by_recipient = 1 WHERE id = %s",
            (cancellation_id,)
        )

        db.commit()

        return {"success": True}

    except mysql.connector.Error as error:
        if db:
            db.rollback()
        return {"success": False, "message": f"Грешка: {error}"}

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


@app.get("/doctor-patient-cancellations/{doctor_id}")
def doctor_patient_cancellations(doctor_id: int):
    """Връща непрочетените отказани часове от пациенти за този лекар."""
    db = None
    cursor = None

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                c.id,
                c.appointment_time,
                c.reason,
                c.created_at,
                u.first_name,
                u.last_name,
                u.phone,
                u.username
            FROM cancellations c
            LEFT JOIN users u ON c.user_id = u.id
            WHERE c.doctor_id = %s
              AND c.cancelled_by = 'patient'
              AND c.seen_by_recipient = 0
            ORDER BY c.appointment_time ASC
            """,
            (doctor_id,)
        )

        rows = cursor.fetchall()

        result = []
        for row in rows:
            first = row.get("first_name") or ""
            last = row.get("last_name") or ""
            patient_name = (first + " " + last).strip()
            if not patient_name:
                patient_name = row.get("username") or "—"

            result.append({
                "id": row["id"],
                "appointment_time": str(row["appointment_time"]),
                "reason": row.get("reason") or "",
                "patient_name": patient_name,
                "patient_phone": row.get("phone") or "",
                "created_at": str(row["created_at"])
            })

        return result

    except mysql.connector.Error as error:
        return {"error": f"Грешка в базата данни: {error}"}

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


@app.post("/doctor-dismiss-cancellation/{cancellation_id}")
def doctor_dismiss_cancellation(cancellation_id: int):
    """Лекарят отбелязва, че е видял отказа от пациент."""
    db = None
    cursor = None

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            "UPDATE cancellations SET seen_by_recipient = 1 WHERE id = %s",
            (cancellation_id,)
        )

        db.commit()

        return {"success": True}

    except mysql.connector.Error as error:
        if db:
            db.rollback()
        return {"success": False, "message": f"Грешка: {error}"}

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()



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



@app.get("/doctors")
def get_doctors():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM doctors")
    doctors = cursor.fetchall()

    cursor.close()
    db.close()


    for d in doctors:
        if "doctor_password" in d:
            d["doctor_password"] = None

    return doctors




@app.get("/doctor-regions")
def get_doctor_regions():
    """Връща всички области, в които има регистрирани лекари."""
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT DISTINCT city
        FROM doctors
        WHERE city IS NOT NULL AND TRIM(city) != ''
        ORDER BY city ASC
        """
    )

    rows = cursor.fetchall()

    cursor.close()
    db.close()

    regions = []

    for row in rows:
        regions.append(row["city"])

    return regions


@app.get("/doctors-data")
def doctors_data(name: str = None, specialty: str = None):
    """Намира лекар по име и специалност (за модала за отказан час)."""
    db = get_db()
    cursor = db.cursor(dictionary=True)

    if name and specialty:
        cursor.execute(
            "SELECT id, name, specialty FROM doctors WHERE name = %s AND specialty = %s LIMIT 1",
            (name, specialty)
        )
    elif name:
        cursor.execute(
            "SELECT id, name, specialty FROM doctors WHERE name = %s LIMIT 1",
            (name,)
        )
    else:
        cursor.close()
        db.close()
        return []

    result = cursor.fetchall()

    cursor.close()
    db.close()

    return result


@app.post("/appointments")
def book_appointment(
    user: str,
    doctor_id: int,
    time: str,
    reason: str = "",
    payment_method: str = "",
    appointment_patient_name: str = "",
    appointment_patient_phone: str = "",
    appointment_note: str = ""
):
    db = None
    cursor = None

    try:
        if not user or user == "undefined" or user == "null":
            return {
                "message": "Няма влязъл потребител. Моля, влезте отново."
            }

        is_allowed_day, validation_message = validate_working_day(time)
        if not is_allowed_day:
            return {
                "message": validation_message
            }

        db = get_db()
        cursor = db.cursor(dictionary=True)

        ensure_appointment_extra_columns(cursor)
        ensure_doctor_day_offs_table(cursor)
        db.commit()

        selected_date = parse_appointment_datetime(time).date().strftime("%Y-%m-%d")
        if is_doctor_day_off(cursor, doctor_id, selected_date):
            return {
                "message": "Лекарят не приема пациенти на тази дата. Моля, изберете друг ден."
            }

        cursor.execute(
            "SELECT id FROM users WHERE username = %s",
            (user,)
        )

        existing_user = cursor.fetchone()

        if not existing_user:
            return {
                "message": "Потребителят не е намерен."
            }

        user_id = existing_user["id"]

        cursor.execute(
            "SELECT id FROM doctors WHERE id = %s",
            (doctor_id,)
        )

        existing_doctor = cursor.fetchone()

        if not existing_doctor:
            return {
                "message": "Избраният лекар не е намерен."
            }

        cursor.execute(
            """
            SELECT id
            FROM appointments
            WHERE doctor_id = %s AND time = %s
            """,
            (doctor_id, time)
        )

        existing_appointment = cursor.fetchone()

        if existing_appointment:
            return {
                "message": "Този час вече е зает"
            }

        cursor.execute(
            """
            INSERT INTO appointments
            (user_id, doctor_id, time, reason, payment_method,
             appointment_patient_name, appointment_patient_phone, appointment_note)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                doctor_id,
                time,
                reason,
                payment_method,
                appointment_patient_name,
                appointment_patient_phone,
                appointment_note
            )
        )

        db.commit()

        return {
            "message": "Часът е записан успешно"
        }

    except mysql.connector.Error as error:
        if db:
            db.rollback()

        return {
            "message": f"Грешка в базата данни: {error}"
        }

    except Exception as error:
        if db:
            db.rollback()

        return {
            "message": f"Възникна грешка при записването: {error}"
        }

    finally:
        if cursor:
            cursor.close()

        if db:
            db.close()


@app.get("/appointments")
def get_appointments():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT appointments.id, users.username, doctors.name, appointments.time
        FROM appointments
        JOIN users ON appointments.user_id = users.id
        JOIN doctors ON appointments.doctor_id = doctors.id
        """
    )

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
    """Връща заетите часове (включително заключени от лекаря) за пациентския изглед."""
    try:
        selected_day = datetime.strptime(date, "%Y-%m-%d").date()
        if is_non_working_day(selected_day):
            return ALL_APPOINTMENT_TIMES
    except ValueError:
        return []

    db = get_db()
    cursor = db.cursor(dictionary=True)

    ensure_doctor_day_offs_table(cursor)
    db.commit()

    if is_doctor_day_off(cursor, doctor_id, date):
        cursor.close()
        db.close()
        return ALL_APPOINTMENT_TIMES

    cursor.execute(
        "SELECT time FROM appointments WHERE doctor_id = %s AND time LIKE %s",
        (doctor_id, date + "%")
    )

    results = cursor.fetchall()

    cursor.close()
    db.close()

    busy_times = []

    for row in results:
        full_time = str(row["time"])
        only_time = full_time.split(" ")[1] if " " in full_time else full_time
        
        if only_time.count(":") == 2:
            only_time = ":".join(only_time.split(":")[:2])
        busy_times.append(only_time)

    return busy_times


@app.get("/my-appointments-data")
def my_appointments_data(username: str):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT
            appointments.id,
            appointments.doctor_id,
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
    db = None
    cursor = None

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            "SELECT id FROM users WHERE username = %s",
            (data.username,)
        )
        current_user = cursor.fetchone()

        if not current_user:
            return {
                "success": False,
                "message": "Потребителят не е намерен."
            }

        current_user_id = current_user["id"]

        cursor.execute(
            "SELECT id FROM users WHERE email = %s AND id != %s",
            (data.email, current_user_id)
        )
        if cursor.fetchone():
            return {
                "success": False,
                "message": "Този имейл вече се използва от друг профил."
            }

        cursor.execute(
            "SELECT id FROM doctors WHERE email = %s",
            (data.email,)
        )
        if cursor.fetchone():
            return {
                "success": False,
                "message": "Този имейл вече се използва от лекарски профил."
            }

        cursor.execute(
            "SELECT id FROM users WHERE phone = %s AND id != %s",
            (data.phone, current_user_id)
        )
        if cursor.fetchone():
            return {
                "success": False,
                "message": "Този телефон вече се използва от друг профил."
            }

        cursor.execute(
            "SELECT id FROM doctors WHERE phone = %s",
            (data.phone,)
        )
        if cursor.fetchone():
            return {
                "success": False,
                "message": "Този телефон вече се използва от лекарски профил."
            }

        cursor.execute(
            """
            UPDATE users
            SET
                first_name = %s,
                last_name = %s,
                email = %s,
                phone = %s,
                city = %s
            WHERE username = %s
            """,
            (
                data.first_name,
                data.last_name,
                data.email,
                data.phone,
                data.city,
                data.username
            )
        )

        db.commit()

        if cursor.rowcount == 0:
            return {
                "success": False,
                "message": "Потребителят не е намерен"
            }

        return {
            "success": True,
            "message": "Профилът е обновен успешно"
        }

    except mysql.connector.Error as error:
        if db:
            db.rollback()

        return {
            "success": False,
            "message": f"Грешка в базата данни: {error}"
        }

    finally:
        if cursor:
            cursor.close()

        if db:
            db.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
