from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import uuid
import smtplib
from email.mime.text import MIMEText
import os
import re
import json
import logging
import atexit

# Set up logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24))


def initialize_firebase():
    if os.environ.get('FIREBASE_CREDENTIALS'):
        # For production (Render) - use env variable with full JSON key
        service_account_info = json.loads(os.environ['FIREBASE_CREDENTIALS'])
        cred = credentials.Certificate(service_account_info)
    else:
        # For local development - use the local JSON file
        cred = credentials.Certificate('serviceAccountKey.json')
    
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    return db

# Initialize Firebase
db = initialize_firebase()

# SMTP Gmail Credentials
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "studymatesystem@gmail.com")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD", "dxmc aueb drbm qvnh")

def send_email(user_email, subject, body, retry=1):
    """
    Send an email using Gmail's SMTP server with improved error handling.
    
    Args:
        user_email: Recipient's email address
        subject: Email subject
        body: Email body content
        retry: Number of retry attempts (default 1)
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    
    # Email validation regex pattern
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    # Validate email format before attempting to send
    if not re.match(email_pattern, user_email):
        logger.error(f"Invalid email format: {user_email}")
        return False
    
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = SENDER_EMAIL
        msg['To'] = user_email

        # Connect to Gmail SMTP server
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, user_email, msg.as_string())
        server.quit()

        logger.info(f"Email sent successfully to {user_email}")
        return True
        
    except smtplib.SMTPRecipientsRefused as e:
        logger.error(f"Email address rejected by server: {user_email}. Error: {e}")
        return False
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP Authentication error: {e}")
        return False
        
    except smtplib.SMTPException as e:
        logger.error(f"SMTP Error sending email: {e}")
        # Try again if we have retries left
        if retry > 0:
            logger.info(f"Retrying... ({retry} attempts left)")
            return send_email(user_email, subject, body, retry-1)
        return False
        
    except Exception as e:
        logger.error(f"Unexpected error sending email: {e}")
        return False

# Route definitions remain the same...
@app.route('/')
def base():
    return render_template('base.html')

@app.route('/ping')
def ping():
    """Health check endpoint for keeping the service alive"""
    return 'pong', 200

def validate_email(email):
    """
    Validate email format using regex.
    
    Args:
        email: Email address to validate
        
    Returns:
        bool: True if valid, False otherwise
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

def validate_name(name):
    """Validate that name contains only letters and spaces."""
    return bool(re.match(r'^[A-Za-z\s]+$', name))

def validate_student_id(student_id):
    """
    Validate student ID format:
    - Should not contain repeated digits like 11111111, 22222222, etc.
    - Should start with letters followed by 9 numbers (e.g., UA202200077)
    """
    # Check if it starts with letters followed by exactly 9 numbers
    if not re.match(r'^[A-Za-z]+\d{9}$', student_id):
        return False
        
    # Check for repeated sequences of digits (e.g., 11111111)
    digit_part = re.search(r'\d+', student_id).group()
    
    # Check if any digit repeats more than 4 times consecutively
    for digit in '0123456789':
        if digit * 5 in digit_part:  # If any digit repeats 5 or more times
            return False
            
    return True

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        student_id = request.form["student_id"]
        gmail = request.form["gmail"]
        age = request.form["age"]
        
        # Validate name
        if not validate_name(name):
            return render_template("register.html", error="Name should contain only letters and spaces.")
            
        # Validate student ID
        if not validate_student_id(student_id):
            return render_template("register.html", 
                error="Invalid student ID format. ID should start with letters followed by 9 numbers (e.g., UA202200077) and should not contain repetitive digits.")
        
        # Validate email
        if not validate_email(gmail):
            return render_template("register.html", error="Invalid email format. Please enter a valid email address.")
            
        # Check if email already exists
        existing_users = db.collection("users").where("gmail", "==", gmail).get()
        if len(list(existing_users)) > 0:
            return render_template("register.html", error="Email already registered. Please use a different email.")
        
        # Check if student ID already exists
        existing_id = db.collection("users").document(student_id).get()
        if existing_id.exists:
            return render_template("register.html", error="Student ID already registered. Please check your ID.")
        
        # Validate age (must be a 2-digit number)
        try:
            age_int = int(age)
            if age_int < 10 or age_int > 99:
                return render_template("register.html", error="Age must be a 2-digit number (10-99).")
        except ValueError:
            return render_template("register.html", error="Age must be a valid number.")
        
        db.collection("users").document(student_id).set({"name": name, "gmail": gmail, "age": age})
        
        # Send a welcome email to verify the address works
        welcome_subject = "Welcome to StudyMate!"
        welcome_body = f"""
Hello {name},

Welcome to StudyMate! Your account has been successfully created.
This email confirms that your email address is working correctly.

Best regards,
StudyMate System
        """
        
        if send_email(gmail, welcome_subject, welcome_body):
            logger.info(f"Welcome email sent to {gmail}")
        else:
            logger.warning(f"Failed to send welcome email to {gmail}")
            # You might want to flag this account for email verification issues
        
        return redirect(url_for("login"))
    return render_template("register.html")

# All other route handlers remain unchanged...
@app.route("/update_user", methods=["POST"])
def update_user():
    if "user" not in session:
        return redirect(url_for("login"))
    # Rest of the function remains the same...

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        student_id = request.form["student_id"]
        
        # Add validation for login too
        if not validate_student_id(student_id):
            return render_template("login.html", error="Invalid student ID format.")
            
        user = db.collection("users").document(student_id).get()
        if user.exists:
            session["user"] = student_id
            return redirect(url_for("dashboard"))
        else:
            return render_template("login.html", error="Student ID not found. Please check your ID or register.")
    return render_template("login.html")

@app.route("/get_user_info")
def get_user_info():
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 403
        
    user_id = session["user"]
    user_doc = db.collection("users").document(user_id).get()
    
    if not user_doc.exists:
        return jsonify({"error": "User not found"}), 404
        
    user_data = user_doc.to_dict()
    # Add the student_id to the response
    user_data["student_id"] = user_id
    
    return jsonify(user_data)


@app.route("/edit_task", methods=["POST"])
def edit_task():
    if "user" not in session:
        return redirect(url_for("login"))
        
    user_id = session["user"]
    task_id = request.form.get("task_id")
    title = request.form.get("title")
    task_type = request.form.get("type")
    subject = request.form.get("subject", "")
    date = request.form.get("date")
    time = request.form.get("time")
    priority = request.form.get("priority")
    
    if not task_id or not title or not task_type or not date or not time or not priority:
        return "Missing required fields", 400
        
    # Convert time to AM/PM format
    time_obj = datetime.strptime(time, "%H:%M")
    time_am_pm = time_obj.strftime("%I:%M %p")
    
    # Get the user's email
    user = db.collection("users").document(user_id).get().to_dict()
    user_name = user.get("name", "") 
    
    # Update the task
    task_ref = db.collection("users").document(user_id).collection("tasks").document(task_id)
    task_ref.update({
        "title": title,
        "type": task_type,
        "subject": subject,
        "due": date,
        "time": time_am_pm,
        "priority": priority,
        "gmail": user["gmail"]
    })
    
    # Send confirmation email about the task update
    try:
        subject_line = f"Task Updated: {title}"
        body = f"""
Hello, {user_name},

One of your task has been updated:

Task: {title}
Subject: {subject if subject else 'N/A'}
Type: {task_type}
Due Date: {date} at {time_am_pm}
Priority: {priority}

Best regards,
StudyMate System
        """
        
        send_email(user["gmail"], subject_line, body)
        logger.info(f"Task update email sent for task: {title}")
    except Exception as e:
        logger.error(f"Error sending task update email: {e}")
    
    return redirect(url_for("dashboard"))

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("base"))

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    
    user_id = session["user"]
    tasks = db.collection("users").document(user_id).collection("tasks").stream()
    return render_template("dashboard.html", tasks=[t.to_dict() for t in tasks])

@app.route("/add_task", methods=["POST"])
def add_task():
    if "user" not in session:
        return redirect(url_for("login"))

    title = request.form.get("title")
    task_type = request.form.get("type")
    subject = request.form.get("subject", "")
    date = request.form.get("date")
    time = request.form.get("time")
    priority = request.form.get("priority")

    if not title or not task_type or not date or not time or not priority:
        logger.warning("Missing required fields!")
        return "Missing required fields", 400

    student_id = session["user"]
    user = db.collection("users").document(student_id).get().to_dict()
    
    # Verify user has a valid email
    user_email = user.get("gmail", "")
    if not user_email or not validate_email(user_email):
        # Store the task but flag that email notifications might fail
        email_verified = False
    else:
        email_verified = True
    
    time_obj = datetime.strptime(time, "%H:%M")
    time_am_pm = time_obj.strftime("%I:%M %p")

    task_id = str(uuid.uuid4())
    
    # Create the task document with email verification status
    task_data = {
        "id": task_id,
        "title": title,
        "type": task_type,
        "subject": subject,
        "due": date,
        "time": time_am_pm,
        "priority": priority,
        "done": False,
        "reminder_count": 0,
        "same_day_reminder_count": 0,
        "overdue_reminder_count": 0,
        "last_reminder_time": None,
        "gmail": user_email,
        "email_verified": email_verified
    }
    
    # Save the task to the database
    db.collection("users").document(student_id).collection("tasks").document(task_id).set(task_data)
    
    # Send confirmation email if email is verified
    if email_verified:
        user_name = user.get("name", "")
        subject_line = f"New Task Created: {title}"
        body = f"""
Hello {user_name},

You have successfully created a new task:

Task: {title}
Subject: {subject if subject else 'N/A'}
Type: {task_type}
Due Date: {date} at {time_am_pm}
Priority: {priority}

Best regards,
StudyMate System
        """
        
        email_success = send_email(user_email, subject_line, body)
        
        # If email failed, update the task to reflect this
        if not email_success:
            db.collection("users").document(student_id).collection("tasks").document(task_id).update({
                "email_verified": False
            })
    
    return redirect(url_for("dashboard"))

@app.route("/complete_task/<task_id>")
def complete_task(task_id):
    if "user" not in session:
        return redirect(url_for("login"))
        
    user_id = session["user"]
    
    # Get the task to send a completion confirmation
    task_ref = db.collection("users").document(user_id).collection("tasks").document(task_id)
    task = task_ref.get().to_dict()

    user = db.collection("users").document(user_id).get().to_dict()
    user_name = user.get("name", "")
    
    if task and not task.get("done", False):
        # Mark the task as done
        task_ref.update({
            "done": True,
            "completed_date": datetime.now().strftime("%Y-%m-%d"),
            "completed_time": datetime.now().strftime("%I:%M %p")
        })
        
        # Send completion confirmation email if there's a gmail address
        if "gmail" in task:
            subject = f"✅ Task Completed: {task.get('title', 'Task')}"
            body = f"""
Hello, {user_name},

Great job! You've completed One of your task:

Task Title: {task.get('title', 'Task')}
Subject: {task.get('subject', 'N/A')}
Priority: {task.get('priority', 'N/A')}
Due Date: {task.get('due', 'N/A')} at {task.get('time', 'N/A')}
Completed: {datetime.now().strftime("%Y-%m-%d at %I:%M %p")}

Keep up the good work!

Best regards,
StudyMate System
            """
            
            try:
                send_email(task["gmail"], subject, body)
                logger.info(f"Completion email sent for task: {task.get('title')}")
            except Exception as e:
                logger.error(f"Error sending completion email: {e}")
    
    return redirect(url_for("dashboard"))

@app.route("/delete_task/<task_id>")
def delete_task(task_id):
    if "user" not in session:
        return redirect(url_for("login"))
        
    user_id = session["user"]
    
    # Get the task for sending a deletion notification
    task_ref = db.collection("users").document(user_id).collection("tasks").document(task_id)
    task = task_ref.get().to_dict()

    user = db.collection("users").document(user_id).get().to_dict()
    user_name = user.get("name", "")
    
    if task:
        # Delete the task from the database
        task_ref.delete()
        
        # Send deletion confirmation email if there's a gmail address
        if "gmail" in task:
            subject = f"Task Deleted: {task.get('title', 'Task')}"
            body = f"""
Hello, {user_name},

One of your task has been deleted:

Task Title: {task.get('title', 'Task')}
Subject: {task.get('subject', 'N/A')}
Priority: {task.get('priority', 'N/A')}
Due Date: {task.get('due', 'N/A')} at {task.get('time', 'N/A')}
Deleted: {datetime.now().strftime("%Y-%m-%d at %I:%M %p")}

Best regards,
StudyMate System
            """
            
            try:
                send_email(task["gmail"], subject, body)
                logger.info(f"Deletion email sent for task: {task.get('title')}")
            except Exception as e:
                logger.error(f"Error sending deletion email: {e}")
    
    return redirect(url_for("dashboard"))
    
@app.route("/get_tasks")
def get_tasks():
    if "user" not in session:
        return jsonify([]), 403

    user_id = session["user"]
    user_tasks = db.collection("users").document(user_id).collection("tasks").stream()

    events = []
    for task in user_tasks:
        data = task.to_dict()
        if "due" in data and "time" in data:
            try:
                # Debug
                logger.debug(f"Processing task for calendar: {data.get('title')}, due: {data.get('due')}, time: {data.get('time')}")
                
                # Parse date and time properly
                due_date = data.get("due")
                time_str = data.get("time", "00:00")
                
                # Handle time format (convert "1:30 PM" format to "13:30" format)
                try:
                    # First, try to parse time in "1:30 PM" format
                    time_obj = datetime.strptime(time_str, "%I:%M %p")
                    time_24h = time_obj.strftime("%H:%M")
                except ValueError:
                    # If that fails, assume it's already in 24-hour format
                    time_24h = time_str
                
                # Format for FullCalendar ISO8601 format (YYYY-MM-DDThh:mm:ss)
                start_datetime = f"{due_date}T{time_24h.replace(' ', '')}"
                
                # Create event object
                event = {
                    "id": data.get("id", task.id),
                    "title": data.get("title", "No Title"),
                    "start": start_datetime,
                    "allDay": False,
                    "extendedProps": {
                        "priority": data.get("priority", "low"),
                        "type": data.get("type", ""),
                        "subject": data.get("subject", "")
                    }
                }
                
                # Set color based on priority
                if data.get("priority") == "high":
                    event["backgroundColor"] = "#dc2626"  # red
                elif data.get("priority") == "medium":
                    event["backgroundColor"] = "#f59e0b"  # yellow
                else:
                    event["backgroundColor"] = "#10b981"  # green
                
                events.append(event)
                logger.debug(f"Added event: {event}")
            except Exception as e:
                logger.error(f"Error processing task for calendar: {e}")
                continue

    logger.info(f"Returning {len(events)} events to calendar")
    return jsonify(events)

def check_reminders():
    """Check for tasks that need reminders with enhanced reminder schedule."""
    now = datetime.now()
    logger.info(f"Running reminder check at {now}")

    try:
        users = db.collection("users").get()
        for user_doc in users:
            user_id = user_doc.id
            tasks_ref = db.collection("users").document(user_id).collection("tasks")
            tasks = tasks_ref.stream()
            user_doc_data = db.collection("users").document(user_id).get()
            
            if not user_doc_data.exists:
                logger.warning(f"User document {user_id} not found")
                continue
                
            user = user_doc_data.to_dict()
            if not user:
                logger.warning(f"User data empty for {user_id}")
                continue
                
            user_name = user.get("name", "")
            user_email = user.get("gmail", "")
            
            # Verify user has valid email
            if not user_email or not validate_email(user_email):
                logger.warning(f"Invalid or missing email for user {user_id}: {user_email}")
                continue

            for task in tasks:
                data = task.to_dict()

                if not data:
                    logger.warning(f"Empty task document {task.id}")
                    continue

                # Check if task is already done
                if data.get("done", False):
                    continue

                # Check if email is valid for notifications
                task_email = data.get("gmail", user_email)
                if not task_email or not validate_email(task_email):
                    logger.warning(f"Invalid email for task {task.id}: {task_email}")
                    # Update the task to reflect this
                    tasks_ref.document(task.id).update({
                        "email_verified": False
                    })
                    continue
                
                # Reset email_verified to True if it was previously false but email is now valid
                if data.get("email_verified") is False and validate_email(task_email):
                    tasks_ref.document(task.id).update({
                        "email_verified": True
                    })

                try:
                    due_date_str = data.get("due")
                    due_time_str = data.get("time")
                    priority = data.get("priority")
                    title = data.get("title", "No Title")
                    
                    # Get or initialize reminder counters
                    reminder_count = data.get("reminder_count", 0)
                    same_day_reminder_count = data.get("same_day_reminder_count", 0)
                    last_reminder_time = data.get("last_reminder_time")
                    overdue_reminder_count = data.get("overdue_reminder_count", 0)
                    
                    if last_reminder_time:
                        try:
                            # Convert string timestamp to datetime object
                            last_reminder_time = datetime.fromisoformat(last_reminder_time)
                        except (ValueError, TypeError):
                            logger.error(f"Invalid last_reminder_time format for task {task.id}")
                            last_reminder_time = None

                    if not due_date_str or not due_time_str or not priority:
                        logger.warning(f"Skipping incomplete task {task.id}: Missing required fields")
                        continue

                    # Debug prints
                    logger.debug(f"Processing task: {title}, due: {due_date_str} {due_time_str}")

                    # Combine date and time into full datetime with improved parsing
                    try:
                        # Debug prints
                        logger.debug(f"Parsing datetime from: '{due_date_str}' '{due_time_str}'")
                        
                        # Try different time formats - starting with AM/PM format
                        try:
                            # First try standard AM/PM format
                            full_due_datetime = datetime.strptime(f"{due_date_str} {due_time_str}", "%Y-%m-%d %I:%M %p")
                            logger.debug(f"Successfully parsed as AM/PM format: {full_due_datetime}")
                        except ValueError:
                            # Try with uppercase AM/PM
                            try:
                                full_due_datetime = datetime.strptime(f"{due_date_str} {due_time_str}", "%Y-%m-%d %I:%M %P")
                                logger.debug(f"Successfully parsed as uppercase AM/PM format: {full_due_datetime}")
                            except ValueError:
                                # Try without space between time and AM/PM
                                try:
                                    full_due_datetime = datetime.strptime(f"{due_date_str} {due_time_str}", "%Y-%m-%d %I:%M%p")
                                    logger.debug(f"Successfully parsed as no-space AM/PM format: {full_due_datetime}")
                                except ValueError:
                                    # Try 24-hour format
                                    try:
                                        full_due_datetime = datetime.strptime(f"{due_date_str} {due_time_str}", "%Y-%m-%d %H:%M")
                                        logger.debug(f"Successfully parsed as 24-hour format: {full_due_datetime}")
                                    except ValueError:
                                        # Last resort - try to extract time components manually
                                        logger.debug(f"Standard parsing failed. Attempting manual parsing for time: '{due_time_str}'")
                                        
                                        # Strip any whitespace
                                        time_clean = due_time_str.strip()
                                        
                                        # Look for AM/PM indicator
                                        is_pm = False
                                        if "PM" in time_clean.upper():
                                            is_pm = True
                                            time_clean = time_clean.upper().replace("PM", "").strip()
                                        elif "AM" in time_clean.upper():
                                            time_clean = time_clean.upper().replace("AM", "").strip()
                                        
                                        # Split hours and minutes
                                        if ":" in time_clean:
                                            hour_str, minute_str = time_clean.split(":")
                                            hour = int(hour_str)
                                            minute = int(minute_str)
                                            
                                            # Convert to 24-hour format if PM
                                            if is_pm and hour < 12:
                                                hour += 12
                                            elif not is_pm and hour == 12:
                                                hour = 0
                                                
                                            # Create datetime object
                                            date_obj = datetime.strptime(due_date_str, "%Y-%m-%d")
                                            full_due_datetime = date_obj.replace(hour=hour, minute=minute)
                                            logger.debug(f"Manual parsing successful: {full_due_datetime}")
                                        else:
                                            # If no colon, assume it's just hours
                                            hour = int(time_clean)
                                            if is_pm and hour < 12:
                                                hour += 12
                                            elif not is_pm and hour == 12:
                                                hour = 0
                                                
                                            date_obj = datetime.strptime(due_date_str, "%Y-%m-%d")
                                            full_due_datetime = date_obj.replace(hour=hour, minute=0)
                                            logger.debug(f"Manual parsing (hours only) successful: {full_due_datetime}")
                    except ValueError as e:
                        logger.error(f"Error parsing datetime for task {task.id}: {e}")
                        continue

                    # How much time is left
                    time_remaining = full_due_datetime - now
                    days_remaining = time_remaining.total_seconds() / (24 * 3600)  # Convert to days
                    hours_remaining = time_remaining.total_seconds() / 3600
                    minutes_remaining = time_remaining.total_seconds() / 60

                    # Check if task is past due
                    if days_remaining < 0:
                        # Task is overdue - send reminders with proper spacing
                        days_overdue = abs(days_remaining)
                        logger.info(f"Task '{title}' is past due by {days_overdue:.2f} days")
                        
                        # Get time since last overdue reminder
                        time_since_last_reminder = float('inf')
                        if last_reminder_time:
                            time_since_last_reminder = (now - last_reminder_time).total_seconds() / 3600  # Hours
                        
                        # Check if we should send another overdue reminder
                        # Logic: First reminder immediately when due, then every 24 hours for first 3 days,
                        # then every 2 days for next 3 reminders, then weekly
                        should_send_overdue = False
                        
                        if overdue_reminder_count == 0:
                            # First overdue notification
                            should_send_overdue = True
                            reminder_frequency = "first"
                        elif overdue_reminder_count < 4 and time_since_last_reminder >= 24:
                            # Daily reminders for first 3 days
                            should_send_overdue = True
                            reminder_frequency = "daily"
                        elif 3 <= overdue_reminder_count < 7 and time_since_last_reminder >= 48:
                            # Every 2 days for next 3 reminders
                            should_send_overdue = True
                            reminder_frequency = "every 2 days"
                        elif overdue_reminder_count >= 7 and time_since_last_reminder >= 168:
                            # Weekly reminders after first week
                            should_send_overdue = True
                            reminder_frequency = "weekly"
                        
                        if should_send_overdue:
                            # Send overdue notification
                            subject = f"OVERDUE TASK: {title}"
                            body = f"""
Hello {user_name},

This is a reminder that the following task is OVERDUE:

Task: {title}
Subject: {data.get('subject', 'N/A')}
Type: {data.get('type', 'N/A')}
Due Date: {due_date_str} at {due_time_str} (was due {days_overdue:.1f} days ago)
Priority: {priority}

Please complete this task as soon as possible or update its due date if needed.

Best regards,
StudyMate System
                            """
                            
                            if send_email(task_email, subject, body):
                                logger.info(f"Sent overdue reminder ({reminder_frequency}) for task '{title}' to {task_email}")
                                
                                # Update task counters
                                tasks_ref.document(task.id).update({
                                    "overdue_reminder_count": overdue_reminder_count + 1,
                                    "reminder_count": reminder_count + 1,
                                    "last_reminder_time": now.isoformat()
                                })
                            else:
                                logger.error(f"Failed to send overdue reminder for task '{title}' to {task_email}")
                    
                    # Task is not yet due - check if we need to send an upcoming reminder
                    else:
                        logger.debug(f"Task '{title}' has {days_remaining:.2f} days remaining")
                        
                        # Get time since last reminder
                        time_since_last_reminder = float('inf')
                        if last_reminder_time:
                            time_since_last_reminder = (now - last_reminder_time).total_seconds() / 3600  # Hours
                        
                        # Determine if we should send a reminder based on priority and time remaining
                        should_send_reminder = False
                        reminder_type = None
                        
                        # Check for same-day reminders (tasks due today)
                        if 0 <= days_remaining < 1:
                            # Task is due today
                            
                            # Same day reminder schedule:
                            # High priority: 6 hours before, 3 hours before, 1 hour before
                            # Medium priority: 6 hours before, 1 hour before
                            # Low priority: 3 hours before
                            
                            if priority == "high":
                                if (6 <= hours_remaining < 7 and same_day_reminder_count == 0) or \
                                   (3 <= hours_remaining < 4 and same_day_reminder_count == 1) or \
                                   (1 <= hours_remaining < 2 and same_day_reminder_count == 2):
                                    should_send_reminder = True
                                    reminder_type = f"{int(hours_remaining)} hour"
                            
                            elif priority == "medium":
                                if (6 <= hours_remaining < 7 and same_day_reminder_count == 0) or \
                                   (1 <= hours_remaining < 2 and same_day_reminder_count == 1):
                                    should_send_reminder = True
                                    reminder_type = f"{int(hours_remaining)} hour"
                            
                            elif priority == "low":
                                if 3 <= hours_remaining < 4 and same_day_reminder_count == 0:
                                    should_send_reminder = True
                                    reminder_type = f"{int(hours_remaining)} hour"
                        
                        # Check for advanced reminders
                        # High priority: 7 days, 3 days, 1 day before
                        # Medium priority: 5 days, 1 day before
                        # Low priority: 3 days before
                        elif priority == "high":
                            if (7 <= days_remaining < 7.1 and reminder_count == 0) or \
                               (3 <= days_remaining < 3.1 and reminder_count == 1) or \
                               (1 <= days_remaining < 1.1 and reminder_count == 2):
                                should_send_reminder = True
                                reminder_type = f"{int(days_remaining)} day"
                        
                        elif priority == "medium":
                            if (5 <= days_remaining < 5.1 and reminder_count == 0) or \
                               (1 <= days_remaining < 1.1 and reminder_count == 1):
                                should_send_reminder = True
                                reminder_type = f"{int(days_remaining)} day"
                        
                        elif priority == "low":
                            if 3 <= days_remaining < 3.1 and reminder_count == 0:
                                should_send_reminder = True
                                reminder_type = f"{int(days_remaining)} day"
                        
                        # Send reminder if conditions are met
                        if should_send_reminder:
                            logger.info(f"Sending {reminder_type} reminder for task '{title}'")
                            
                            subject = f"Reminder: {title} - Due in {reminder_type}"
                            body = f"""
Hello {user_name},

This is a friendly reminder about your upcoming task:

Task: {title}
Subject: {data.get('subject', 'N/A')}
Type: {data.get('type', 'N/A')}
Due Date: {due_date_str} at {due_time_str}
Priority: {priority}

This task is due in {reminder_type}{"s" if int(float(reminder_type.split()[0])) > 1 else ""}.

Best regards,
StudyMate System
                            """
                            
                            if send_email(task_email, subject, body):
                                logger.info(f"Sent {reminder_type} reminder for task '{title}' to {task_email}")
                                
                                # Update task counters
                                update_data = {
                                    "reminder_count": reminder_count + 1,
                                    "last_reminder_time": now.isoformat()
                                }
                                
                                # Update same-day reminders if applicable
                                if 0 <= days_remaining < 1:
                                    update_data["same_day_reminder_count"] = same_day_reminder_count + 1
                                
                                tasks_ref.document(task.id).update(update_data)
                            else:
                                logger.error(f"Failed to send reminder for task '{title}' to {task_email}")
                
                except Exception as e:
                    logger.error(f"Error processing reminders for task {task.id}: {e}")
                    
    except Exception as e:
        logger.error(f"Error in reminder check: {e}")

# Initialize the scheduler
def init_scheduler():
    """Initialize and start the background scheduler"""
    scheduler = BackgroundScheduler()
    # Schedule the check_reminders function to run every 5 minutes
    scheduler.add_job(func=check_reminders, trigger="interval", minutes=25)
    # Start the scheduler
    scheduler.start()
    logger.info("Scheduler started, running check_reminders every 5 minutes")
    # Register a shutdown function to close scheduler on exit
    atexit.register(lambda: scheduler.shutdown())
    return scheduler

# Start the scheduler when the app is launched
scheduler = init_scheduler()

# For Render web services - this is critical
if __name__ == "__main__":
    # Set port for Render compatibility
    port = int(os.environ.get("PORT", 5000))
    
    # Initialize the scheduler
    scheduler = init_scheduler()
    
    # Run the Flask app
    app.run(host="0.0.0.0", port=port)
