from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import uuid
import smtplib
import pytz
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

@app.route("/update_user", methods=["POST"])
def update_user():
    if "user" not in session:
        return redirect(url_for("login"))
        
    user_id = session["user"]
    name = request.form.get("name")
    gmail = request.form.get("gmail")
    age = request.form.get("age")
    student_id = request.form.get("student_id")  # Get student_id for updating
    
    if not name or not gmail or not age:
        return "Missing required fields", 400
    
    # Validate name
    if not validate_name(name):
        return "Name should contain only letters and spaces", 400
    
    # Validate email
    if not validate_email(gmail):
        return "Invalid email format", 400
    
    # Validate age (must be a 2-digit number)
    try:
        age_int = int(age)
        if age_int < 10 or age_int > 99:
            return "Age must be a 2-digit number (10-99)", 400
    except ValueError:
        return "Age must be a valid number", 400
        
    # If student_id is provided and being updated
    if student_id and student_id != user_id:
        # Validate the new student ID
        if not validate_student_id(student_id):
            return "Invalid student ID format. ID should start with letters followed by 9 numbers (e.g., UA202200077) and should not contain repetitive digits.", 400
            
        # Check if the new student_id already exists
        doc_ref = db.collection("users").document(student_id).get()
        if doc_ref.exists:
            return "Student ID already exists", 400
            
        # Create a new document with the updated student_id
        user_data = db.collection("users").document(user_id).get().to_dict()
        user_data.update({
            "name": name,
            "gmail": gmail,
            "age": age
        })
        
        # Start a transaction to update student_id
        transaction = db.transaction()
        
        @firestore.transactional
        def update_in_transaction(transaction, old_id, new_id, data):
            # Create new document
            transaction.set(db.collection("users").document(new_id), data)
            
            # Delete old document
            transaction.delete(db.collection("users").document(old_id))
            
            # Update session
            session["user"] = new_id
            
            return True
            
        update_success = update_in_transaction(transaction, user_id, student_id, user_data)
        
        if not update_success:
            return "Failed to update student ID", 500
            
        # Update user_id for tasks and other operations
        user_id = student_id
    else:
        # Update the user document with the same student_id
        db.collection("users").document(user_id).update({
            "name": name,
            "gmail": gmail,
            "age": age
        })
    
    # Update gmail in all tasks
    tasks_ref = db.collection("users").document(user_id).collection("tasks")
    tasks = tasks_ref.stream()
    
    for task in tasks:
        tasks_ref.document(task.id).update({"gmail": gmail})
    
    return redirect(url_for("dashboard"))


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

@app.route("/delete_user", methods=["POST"])
def delete_user():
    """Delete a user account and all associated tasks"""
    if "user" not in session:
        return redirect(url_for("login"))
    
    user_id = session["user"]
    
    try:
        # Get user info for confirmation email before deletion
        user_doc = db.collection("users").document(user_id).get()
        if not user_doc.exists:
            logger.error(f"User {user_id} not found during deletion attempt")
            return "User not found", 404
        
        user_data = user_doc.to_dict()
        user_email = user_data.get("gmail", "")
        user_name = user_data.get("name", "")
        
        # Start a transaction for atomically deleting user data
        transaction = db.transaction()
        
        @firestore.transactional
        def delete_user_in_transaction(transaction, uid, email, name):
            # Get all tasks for the user
            tasks_ref = db.collection("users").document(uid).collection("tasks")
            tasks = tasks_ref.stream()
            
            # Delete all tasks
            for task in tasks:
                transaction.delete(tasks_ref.document(task.id))
                logger.info(f"Deleted task {task.id} for user {uid}")
            
            # Delete user document
            transaction.delete(db.collection("users").document(uid))
            logger.info(f"Deleted user document for {uid}")
            
            # Clear session
            session.pop("user", None)
            
            # Send confirmation email
            if email and validate_email(email):
                subject = "Your StudyMate Account Has Been Deleted"
                body = f"""
Hello {name},

Your StudyMate account has been successfully deleted as requested.
All your account information and tasks have been permanently removed from our system.

If you didn't request this action or have any questions, please contact us on gmail.

Thank you for using StudyMate!

Best regards,
StudyMate System
                """
                
                send_email(email, subject, body)
                logger.info(f"Account deletion confirmation email sent to {email}")
            
            return True
        
        # Execute transaction
        success = delete_user_in_transaction(transaction, user_id, user_email, user_name)
        
        if not success:
            logger.error(f"Failed to delete user {user_id}")
            return "Failed to delete account", 500
        
        # Redirect to base page
        return redirect(url_for("base"))
        
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {e}")
        return "An error occurred while deleting account", 500

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
        if "due" in data:
            try:
                # Debug logging
                logger.debug(f"Processing task: {data.get('title')}")
                logger.debug(f"Raw due date: {data.get('due')}")
                logger.debug(f"Raw time: {data.get('time')}")
                
                # Get the date
                due_date = data.get("due")
                if not due_date:
                    logger.warning(f"No due date for task: {data.get('title')}")
                    continue
                
                # Get and process the time
                time_str = data.get("time")
                processed_time = parse_time_for_calendar(time_str)
                
                # Create the full datetime string for FullCalendar
                if processed_time:
                    # Format: 2025-05-22T14:30:00
                    start_datetime = f"{due_date}T{processed_time}:00"
                    logger.debug(f"Created datetime: {start_datetime}")
                else:
                    # Fallback to all-day event
                    start_datetime = due_date
                    logger.debug(f"Using all-day format: {start_datetime}")
                
                # Create event object
                event = {
                    "id": data.get("id", task.id),
                    "title": data.get("title", "No Title"),
                    "start": start_datetime,
                    "allDay": processed_time is None,  # True if no valid time found
                    "extendedProps": {
                        "priority": data.get("priority", "low"),
                        "type": data.get("type", ""),
                        "subject": data.get("subject", ""),
                        "time": data.get("time", "")  # Keep original for reference
                    }
                }
                
                # Set color based on priority
                priority = data.get("priority", "low").lower()
                if priority == "high":
                    event["backgroundColor"] = "#dc2626"  # red
                    event["borderColor"] = "#dc2626"
                elif priority == "medium":
                    event["backgroundColor"] = "#f59e0b"  # amber
                    event["borderColor"] = "#f59e0b"
                else:
                    event["backgroundColor"] = "#10b981"  # green
                    event["borderColor"] = "#10b981"
                
                event["textColor"] = "#ffffff"
                
                events.append(event)
                logger.debug(f"Successfully added event: {event['title']} at {event['start']}")
                
            except Exception as e:
                logger.error(f"Error processing task '{data.get('title', 'Unknown')}': {str(e)}")
                # Continue processing other tasks instead of failing completely
                continue

    logger.info(f"Returning {len(events)} events to calendar")
    return jsonify(events)


def parse_time_for_calendar(time_str):
    """
    Parse various time formats and return 24-hour format (HH:MM) for FullCalendar
    Returns None if no valid time can be parsed (for all-day events)
    """
    if not time_str or time_str in ['None', 'null', '', 'undefined']:
        return None
    
    time_str = str(time_str).strip()
    
    try:
        # Pattern 1: 12-hour format with AM/PM (e.g., "2:30 PM", "11:45AM", "9 AM")
        import re
        am_pm_pattern = r'(\d{1,2}):?(\d{2})?\s*([AaPp][Mm])'
        am_pm_match = re.search(am_pm_pattern, time_str)
        
        if am_pm_match:
            hours = int(am_pm_match.group(1))
            minutes = int(am_pm_match.group(2)) if am_pm_match.group(2) else 0
            period = am_pm_match.group(3).upper()
            
            # Convert to 24-hour format
            if period == 'PM' and hours != 12:
                hours += 12
            elif period == 'AM' and hours == 12:
                hours = 0
            
            return f"{hours:02d}:{minutes:02d}"
        
        # Pattern 2: 24-hour format (e.g., "14:30", "09:00", "23:45")
        time_24_pattern = r'(\d{1,2}):(\d{2})'
        time_24_match = re.search(time_24_pattern, time_str)
        
        if time_24_match:
            hours = int(time_24_match.group(1))
            minutes = int(time_24_match.group(2))
            
            # Validate ranges
            if 0 <= hours <= 23 and 0 <= minutes <= 59:
                return f"{hours:02d}:{minutes:02d}"
        
        # Pattern 3: Just hours (e.g., "14", "9", "2")
        hour_only_pattern = r'^(\d{1,2})$'
        hour_only_match = re.match(hour_only_pattern, time_str)
        
        if hour_only_match:
            hours = int(hour_only_match.group(1))
            
            # If it's a reasonable hour, use it
            if 0 <= hours <= 23:
                return f"{hours:02d}:00"
            elif 1 <= hours <= 12:
                # Assume PM for afternoon hours
                if hours < 8:
                    hours += 12
                return f"{hours:02d}:00"
        
        # Pattern 4: Try using datetime parsing as fallback
        from datetime import datetime
        
        # Try common formats
        formats_to_try = [
            "%I:%M %p",    # 2:30 PM
            "%I%p",        # 2PM
            "%H:%M",       # 14:30
            "%H",          # 14
        ]
        
        for fmt in formats_to_try:
            try:
                time_obj = datetime.strptime(time_str, fmt)
                return time_obj.strftime("%H:%M")
            except ValueError:
                continue
        
        # If we get here, we couldn't parse the time
        logger.warning(f"Could not parse time string: '{time_str}'")
        return None
        
    except Exception as e:
        logger.error(f"Error parsing time '{time_str}': {str(e)}")
        return None


# Alternative helper function if you prefer a simpler approach
def simple_time_parser(time_str):
    """Simplified time parser - less robust but easier to understand"""
    if not time_str or str(time_str).lower() in ['none', 'null', '']:
        return None
    
    time_str = str(time_str).strip()
    
    # Handle AM/PM format
    if 'AM' in time_str.upper() or 'PM' in time_str.upper():
        try:
            from datetime import datetime
            time_obj = datetime.strptime(time_str, "%I:%M %p")
            return time_obj.strftime("%H:%M")
        except ValueError:
            try:
                # Try without minutes
                time_obj = datetime.strptime(time_str, "%I %p")
                return time_obj.strftime("%H:%M")
            except ValueError:
                pass
    
    # Handle 24-hour format
    if ':' in time_str:
        try:
            parts = time_str.split(':')
            hours = int(parts[0])
            minutes = int(parts[1])
            if 0 <= hours <= 23 and 0 <= minutes <= 59:
                return f"{hours:02d}:{minutes:02d}"
        except (ValueError, IndexError):
            pass
    
    # Default fallback
    return "09:00"  # 9 AM default


# QUICK FIX: Add this to the top of your check_reminders() function
# Replace your existing check_reminders function with this updated version

def check_reminders():
    """Check for tasks that need reminders with timezone fix."""
    
    # TIMEZONE FIX: Get current time in your timezone
    import pytz
    from datetime import datetime, timezone
    
    # Determine your timezone based on your location
    # Since your server is in Oregon (Pacific Time), but you might be elsewhere
    # Uncomment the line that matches your location:
    
    # USER_TIMEZONE = pytz.timezone('US/Pacific')        # Oregon/California
    # USER_TIMEZONE = pytz.timezone('US/Eastern')        # New York/Florida
    # USER_TIMEZONE = pytz.timezone('US/Central')        # Chicago/Texas
    # USER_TIMEZONE = pytz.timezone('US/Mountain')       # Denver/Arizona
    # USER_TIMEZONE = pytz.timezone('Asia/Manila')       # Philippines
    # USER_TIMEZONE = pytz.timezone('Europe/London')     # UK
    # USER_TIMEZONE = pytz.timezone('Asia/Tokyo')        # Japan
    # USER_TIMEZONE = pytz.timezone('Australia/Sydney')  # Australia
    
    # Philippines timezone (UTC+8) - User is in Philippines, server is in US
    USER_TIMEZONE = pytz.timezone('Asia/Manila')
    
    # Get current time in UTC, then convert to your timezone
    utc_now = datetime.now(pytz.UTC)
    now = utc_now.astimezone(USER_TIMEZONE)
    
    logger.info(f"Running reminder check at {now} (Local) / {utc_now} (UTC)")

    try:
        users = db.collection("users").get()
        logger.info(f"Found {len(list(users))} users in the database")
        
        for user_doc in users:
            user_id = user_doc.id
            tasks_ref = db.collection("users").document(user_id).collection("tasks")
            tasks = tasks_ref.stream()
            tasks_list = list(tasks)
            logger.info(f"Found {len(tasks_list)} tasks for user {user_id}")
            
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
            logger.debug(f"Processing tasks for user: {user_name}, email: {user_email}")
            
            # Verify user has valid email
            if not user_email or not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', user_email):
                logger.warning(f"Invalid or missing email for user {user_id}: {user_email}")
                continue

            for task in tasks_list:
                task_id = task.id
                data = task.to_dict()

                if not data:
                    logger.warning(f"Empty task document {task_id}")
                    continue

                # Check if task is already done
                if data.get("done", False):
                    logger.debug(f"Skipping completed task {task_id}")
                    continue

                # Check if email is valid for notifications
                task_email = data.get("gmail", user_email)
                if not task_email or not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', task_email):
                    logger.warning(f"Invalid email for task {task_id}: {task_email}")
                    continue

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
                            # Make timezone-aware if needed
                            if last_reminder_time.tzinfo is None:
                                last_reminder_time = USER_TIMEZONE.localize(last_reminder_time)
                        except (ValueError, TypeError):
                            logger.error(f"Invalid last_reminder_time format for task {task_id}")
                            last_reminder_time = None

                    if not due_date_str or not due_time_str or not priority:
                        logger.warning(f"Skipping incomplete task {task_id}: Missing required fields")
                        continue

                    # TIMEZONE FIX: Parse datetime and make it timezone-aware
                    try:
                        # Parse the datetime without timezone first
                        if "AM" in due_time_str.upper() or "PM" in due_time_str.upper():
                            naive_due_datetime = datetime.strptime(f"{due_date_str} {due_time_str}", "%Y-%m-%d %I:%M %p")
                        else:
                            naive_due_datetime = datetime.strptime(f"{due_date_str} {due_time_str}", "%Y-%m-%d %H:%M")
                        
                        # Make it timezone-aware in the user's timezone
                        full_due_datetime = USER_TIMEZONE.localize(naive_due_datetime)
                        
                        logger.debug(f"Parsed datetime: {naive_due_datetime} -> Timezone-aware: {full_due_datetime}")
                        
                    except ValueError as e:
                        logger.error(f"Error parsing datetime for task {task_id}: {e}")
                        continue

                    # Now both datetimes are timezone-aware and comparable
                    time_remaining = full_due_datetime - now
                    days_remaining = time_remaining.total_seconds() / (24 * 3600)
                    hours_remaining = time_remaining.total_seconds() / 3600
                    minutes_remaining = time_remaining.total_seconds() / 60

                    logger.info(f"Task '{title}' - Days remaining: {days_remaining:.2f}, Hours remaining: {hours_remaining:.2f}")
                    logger.debug(f"Current time: {now}, Due time: {full_due_datetime}")

                    # Check if task is past due
                    if days_remaining < 0:
                        # Task is overdue
                        days_overdue = abs(days_remaining)
                        logger.info(f"Task '{title}' is past due by {days_overdue:.2f} days")
                        
                        # Get time since last overdue reminder
                        time_since_last_reminder = float('inf')
                        if last_reminder_time:
                            time_since_last_reminder = (now - last_reminder_time).total_seconds() / 3600
                        
                        should_send_overdue = False
                        
                        if overdue_reminder_count == 0:
                            should_send_overdue = True
                            reminder_frequency = "first"
                        elif overdue_reminder_count < 4 and time_since_last_reminder >= 24:
                            should_send_overdue = True
                            reminder_frequency = "daily"
                        elif 3 <= overdue_reminder_count < 7 and time_since_last_reminder >= 48:
                            should_send_overdue = True
                            reminder_frequency = "every 2 days"
                        elif overdue_reminder_count >= 7 and time_since_last_reminder >= 168:
                            should_send_overdue = True
                            reminder_frequency = "weekly"
                        
                        if should_send_overdue:
                            logger.info(f"Sending overdue reminder ({reminder_frequency}) for task '{title}'")
                            
                            subject = f"OVERDUE TASK: {title}"
                            body = f"""
Hello {user_name},

This is a reminder that the following task is OVERDUE:

Task: {title}
Subject: {data.get('subject', 'N/A')}
Type: {data.get('type', 'N/A')}
Due Date: {due_date_str} at {due_time_str} (was due {days_overdue:.1f} days ago)
Priority: {priority}

Please complete this task as soon as possible.

Best regards,
StudyMate System
                            """
                            
                            if send_email(task_email, subject, body):
                                logger.info(f"Sent overdue reminder for task '{title}'")
                                tasks_ref.document(task_id).update({
                                    "overdue_reminder_count": overdue_reminder_count + 1,
                                    "reminder_count": reminder_count + 1,
                                    "last_reminder_time": now.isoformat()
                                })
                    
                    # Task is not yet due - check upcoming reminders
                    else:
                        logger.debug(f"Task '{title}' has {days_remaining:.2f} days remaining")
                        
                        # Get time since last reminder
                        time_since_last_reminder = float('inf')
                        if last_reminder_time:
                            time_since_last_reminder = (now - last_reminder_time).total_seconds() / 3600
                        
                        # Determine if we should send a reminder
                        should_send_reminder = False
                        reminder_type = None
                        reminder_urgency = "Reminder"
                        
                        if 0 <= days_remaining < 1:
                            # Task is due today
                            if priority == "high":
                                if 6.8 <= hours_remaining <= 7.2:
                                    should_send_reminder = True
                                    reminder_type = "7 hour"
                                    reminder_urgency = "Upcoming"
                                elif 3.8 <= hours_remaining <= 4.2:
                                    should_send_reminder = True
                                    reminder_type = "4 hour"
                                    reminder_urgency = "Important"
                                elif 1.8 <= hours_remaining <= 2.2:
                                    should_send_reminder = True
                                    reminder_type = "2 hour"
                                    reminder_urgency = "Urgent"
                                elif 0 < hours_remaining < 1:
                                    minutes_since_last_reminder = float('inf')
                                    if last_reminder_time:
                                        minutes_since_last_reminder = (now - last_reminder_time).total_seconds() / 60
                                    
                                    if minutes_since_last_reminder >= 10:
                                        should_send_reminder = True
                                        reminder_type = f"{int(minutes_remaining)} minute"
                                        reminder_urgency = "VERY URGENT"
                            
                            elif priority == "medium":
                                if 5.8 <= hours_remaining <= 7.1:
                                    should_send_reminder = True
                                    reminder_type = f"{int(hours_remaining)} hour"
                                    reminder_urgency = "Upcoming"
                                elif 0.8 <= hours_remaining <= 2.1:
                                    should_send_reminder = True
                                    reminder_type = f"{int(hours_remaining)} hour"
                                    reminder_urgency = "Important"
                            
                            elif priority == "low":
                                if 2.8 <= hours_remaining <= 4.1:
                                    should_send_reminder = True
                                    reminder_type = f"{int(hours_remaining)} hour"
                                    reminder_urgency = "Upcoming"
                        
                        elif priority == "high":
                            if 6.8 <= days_remaining <= 7.2:
                                should_send_reminder = True
                                reminder_type = f"{int(days_remaining)} day"
                                reminder_urgency = "Early"
                            elif 2.8 <= days_remaining <= 3.2:
                                should_send_reminder = True
                                reminder_type = f"{int(days_remaining)} day"
                                reminder_urgency = "Upcoming"
                            elif 0.8 <= days_remaining <= 1.2:
                                should_send_reminder = True
                                reminder_type = f"{int(days_remaining)} day"
                                reminder_urgency = "Important"
                        
                        elif priority == "medium":
                            if 4.8 <= days_remaining <= 5.2:
                                should_send_reminder = True
                                reminder_type = f"{int(days_remaining)} day"
                                reminder_urgency = "Early"
                            elif 0.8 <= days_remaining <= 1.2:
                                should_send_reminder = True
                                reminder_type = f"{int(days_remaining)} day"
                                reminder_urgency = "Important"
                        
                        elif priority == "low":
                            if 2.8 <= days_remaining <= 3.2:
                                should_send_reminder = True
                                reminder_type = f"{int(days_remaining)} day"
                                reminder_urgency = "Upcoming"
                        
                        # Prevent excessive reminders
                        if should_send_reminder and time_since_last_reminder < 1 and hours_remaining >= 2:
                            should_send_reminder = False
                        
                        # Send reminder if conditions are met
                        if should_send_reminder:
                            logger.info(f"Sending {reminder_type} reminder for task '{title}'")
                            
                            if "minute" in reminder_type:
                                subject = f"{reminder_urgency}: {title} - Due in {reminder_type}s"
                            else:
                                subject = f"{reminder_urgency} Reminder: {title} - Due in {reminder_type}"
                            
                            body = f"""
Hello {user_name},

This is a reminder about your upcoming task:

Task: {title}
Subject: {data.get('subject', 'N/A')}
Type: {data.get('type', 'N/A')}
Due Date: {due_date_str} at {due_time_str}
Priority: {priority}

This task is due in {reminder_type}{"s" if "minute" in reminder_type else ""}.

Best regards,
StudyMate System
                            """
                            
                            if send_email(task_email, subject, body):
                                logger.info(f"Sent {reminder_urgency} {reminder_type} reminder for task '{title}'")
                                
                                update_data = {
                                    "reminder_count": reminder_count + 1,
                                    "last_reminder_time": now.isoformat()
                                }
                                
                                if 0 <= days_remaining < 1 and not (priority == "high" and hours_remaining < 1):
                                    update_data["same_day_reminder_count"] = same_day_reminder_count + 1
                                
                                tasks_ref.document(task_id).update(update_data)
                
                except Exception as e:
                    logger.error(f"Error processing reminders for task {task_id}: {e}")
                    
    except Exception as e:
        logger.error(f"Error in reminder check: {e}")

def init_scheduler():
    """Initialize and start the background scheduler"""
    scheduler = BackgroundScheduler()
    # Schedule the check_reminders function to run every 5 minutes
    scheduler.add_job(func=check_reminders, trigger="interval", minutes=5)
    # Start the scheduler
    scheduler.start()
    logger.info("Scheduler started, running check_reminders every 5 minutes")
    # Register a shutdown function to close scheduler on exit
    atexit.register(lambda: scheduler.shutdown())
    return scheduler

# CRITICAL FIX: Initialize scheduler at module level for Render compatibility
# This ensures the scheduler starts when the module is imported by gunicorn
try:
    scheduler = init_scheduler()
    logger.info("Scheduler initialized at module level for production deployment")
except Exception as e:
    logger.error(f"Failed to initialize scheduler: {e}")
    scheduler = None

# For Render web services - this is critical
if __name__ == "__main__":
    # Set port for Render compatibility
    port = int(os.environ.get("PORT", 5000))
    
    # Only initialize scheduler if not already done at module level
    if scheduler is None:
        scheduler = init_scheduler()
    
    # Run the Flask app
    app.run(host="0.0.0.0", port=port)
else:
    # This block runs when imported by gunicorn
    logger.info("App imported by WSGI server (gunicorn)")
    if scheduler is not None:
        logger.info("Scheduler is running in production mode")
