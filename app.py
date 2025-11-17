from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy import text   # for running raw SQL (backup tables + triggers)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///admissions.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'dev-secret'  # change for production

db = SQLAlchemy(app)

# ---------- Models ----------
class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    duration_months = db.Column(db.Integer, nullable=False, default=12)
    seats_total = db.Column(db.Integer, nullable=False, default=30)
    seats_taken = db.Column(db.Integer, nullable=False, default=0)
    description = db.Column(db.String(500), nullable=True)
    applicants = db.relationship('Applicant', backref='course', lazy=True, cascade="all, delete-orphan")

    def seats_available(self):
        return max(0, self.seats_total - self.seats_taken)

class Applicant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(120), nullable=False, unique=True)
    phone = db.Column(db.String(20), nullable=True)
    dob = db.Column(db.String(20), nullable=True)
    application_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    status = db.Column(db.String(30), nullable=False, default='Applied')  # Applied, Shortlisted, Admitted, Rejected
    remarks = db.Column(db.String(400), nullable=True)

@app.context_processor
def inject_models():
    return dict(Course=Course)

@app.context_processor
def utility_processor():
    return dict(now=lambda: datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'))

# ---------- Routes ----------
@app.route('/')
def index():
    courses = Course.query.order_by(Course.name).all()
    applicants_count = Applicant.query.count()
    return render_template('index.html', courses=courses, applicants_count=applicants_count)

# Courses CRUD
@app.route('/courses')
def courses():
    courses = Course.query.order_by(Course.id).all()
    return render_template('courses.html', courses=courses)

@app.route('/courses/add', methods=['GET', 'POST'])
def add_course():
    if request.method == 'POST':
        name = request.form['name'].strip()
        duration = int(request.form.get('duration_months', 12))
        seats = int(request.form.get('seats_total', 30))
        description = request.form.get('description', '').strip()

        if not name:
            flash('Course name is required', 'danger')
            return redirect(url_for('add_course'))

        course = Course(name=name, duration_months=duration, seats_total=seats, description=description)
        db.session.add(course)
        db.session.commit()
        flash('Course added successfully', 'success')
        return redirect(url_for('courses'))
    return render_template('add_course.html')

@app.route('/courses/edit/<int:id>', methods=['GET', 'POST'])
def edit_course(id):
    course = Course.query.get_or_404(id)
    if request.method == 'POST':
        course.name = request.form['name'].strip()
        course.duration_months = int(request.form.get('duration_months', course.duration_months))
        course.seats_total = int(request.form.get('seats_total', course.seats_total))
        course.description = request.form.get('description', course.description)
        # ensure seats_taken <= seats_total
        if course.seats_taken > course.seats_total:
            course.seats_taken = course.seats_total
        db.session.commit()
        flash('Course updated', 'success')
        return redirect(url_for('courses'))
    return render_template('edit_course.html', course=course)

@app.route('/courses/delete/<int:id>', methods=['POST'])
def delete_course(id):
    course = Course.query.get_or_404(id)
    db.session.delete(course)
    db.session.commit()
    flash('Course deleted', 'info')
    return redirect(url_for('courses'))

# Applicants CRUD
@app.route('/applicants')
def applicants():
    applicants = Applicant.query.order_by(Applicant.application_date.desc()).all()
    return render_template('applicants.html', applicants=applicants)

@app.route('/applicants/add', methods=['GET', 'POST'])
def add_applicant():
    courses = Course.query.order_by(Course.name).all()
    if not courses:
        flash('Add a course before creating applicants.', 'warning')
        return redirect(url_for('courses'))

    if request.method == 'POST':
        full_name = request.form['full_name'].strip()
        email = request.form['email'].strip().lower()
        phone = request.form.get('phone', '').strip()
        dob = request.form.get('dob', '').strip()
        course_id = int(request.form['course_id'])
        remarks = request.form.get('remarks', '').strip()

        if not full_name or not email:
            flash('Name and email are required', 'danger')
            return redirect(url_for('add_applicant'))

        if Applicant.query.filter_by(email=email).first():
            flash('An applicant with that email already exists', 'danger')
            return redirect(url_for('add_applicant'))

        applicant = Applicant(full_name=full_name, email=email, phone=phone, dob=dob,
                              course_id=course_id, remarks=remarks)
        db.session.add(applicant)
        db.session.commit()
        flash('Applicant added', 'success')
        return redirect(url_for('applicants'))

    return render_template('add_applicant.html', courses=courses)

@app.route('/applicant/<int:id>')
def view_applicant(id):
    a = Applicant.query.get_or_404(id)
    return render_template('view_applicant.html', a=a)

@app.route('/applicant/update_status/<int:id>', methods=['POST'])
def update_status(id):
    a = Applicant.query.get_or_404(id)
    new_status = request.form.get('status')
    if new_status not in ('Applied', 'Shortlisted', 'Admitted', 'Rejected'):
        flash('Invalid status', 'danger')
        return redirect(url_for('view_applicant', id=id))

    # if moving to Admitted, update seats_taken
    if a.status != 'Admitted' and new_status == 'Admitted':
        course = a.course
        if course.seats_taken >= course.seats_total:
            flash('No seats available in the selected course', 'danger')
            return redirect(url_for('view_applicant', id=id))
        course.seats_taken += 1

    # if moving from Admitted to something else, free a seat
    if a.status == 'Admitted' and new_status != 'Admitted':
        course = a.course
        course.seats_taken = max(0, course.seats_taken - 1)

    a.status = new_status
    a.remarks = request.form.get('remarks', a.remarks)
    db.session.commit()
    flash('Applicant status updated', 'success')
    return redirect(url_for('view_applicant', id=id))

@app.route('/applicant/delete/<int:id>', methods=['POST'])
def delete_applicant(id):
    a = Applicant.query.get_or_404(id)
    # if admitted, free up seat
    if a.status == 'Admitted' and a.course:
        a.course.seats_taken = max(0, a.course.seats_taken - 1)
    db.session.delete(a)
    db.session.commit()
    flash('Applicant deleted', 'info')
    return redirect(url_for('applicants'))

# Reports example route
@app.route('/reports')
def reports():
    # Number of applicants per course
    data = db.session.query(Course.name, db.func.count(Applicant.id)).join(Applicant, isouter=True)\
           .group_by(Course.id).all()
    # counts by status
    status_counts = db.session.query(Applicant.status, db.func.count(Applicant.id)).group_by(Applicant.status).all()
    return render_template('reports.html', data=data, status_counts=status_counts)

# ---------- DB init helper ----------
def init_db():
    # Create main tables
    db.create_all()

    # 1) Create backup table for deleted applicants (if it doesn't exist)
    backup_applicant_sql = """
    CREATE TABLE IF NOT EXISTS deleted_applicants (
      backup_id        INTEGER PRIMARY KEY AUTOINCREMENT,
      applicant_id     INTEGER,
      full_name        TEXT,
      email            TEXT,
      phone            TEXT,
      dob              TEXT,
      application_date DATETIME,
      course_id        INTEGER,
      status           TEXT,
      remarks          TEXT,
      deleted_at       DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """

    # 2) Trigger: AFTER DELETE on applicant -> copy OLD row into deleted_applicants-- NOTE: SQLAlchemy default table name for Applicant is "applicant"
    applicant_trigger_sql = """
    CREATE TRIGGER IF NOT EXISTS trg_backup_applicant_delete
    AFTER DELETE ON applicant
    FOR EACH ROW
    BEGIN
      INSERT INTO deleted_applicants (
        applicant_id,
        full_name,
        email,
        phone,
        dob,
        application_date,
        course_id,
        status,
        remarks,
        deleted_at
      )
      VALUES (
        OLD.id,
        OLD.full_name,
        OLD.email,
        OLD.phone,
        OLD.dob,
        OLD.application_date,
        OLD.course_id,
        OLD.status,
        OLD.remarks,
        CURRENT_TIMESTAMP
      );
    END;
    """

    # 3) Create backup table for deleted courses
    backup_course_sql = """
    CREATE TABLE IF NOT EXISTS deleted_courses (
      backup_id        INTEGER PRIMARY KEY AUTOINCREMENT,
      course_id        INTEGER,
      name             TEXT,
      duration_months  INTEGER,
      seats_total      INTEGER,
      seats_taken      INTEGER,
      description      TEXT,
      deleted_at       DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """

    # 4) Trigger: AFTER DELETE on course -> copy OLD row into deleted_courses
    course_trigger_sql = """
    CREATE TRIGGER IF NOT EXISTS trg_backup_course_delete
    AFTER DELETE ON course
    FOR EACH ROW
    BEGIN
      INSERT INTO deleted_courses (
        course_id,
        name,
        duration_months,
        seats_total,
        seats_taken,
        description,
        deleted_at
      )
      VALUES (
        OLD.id,
        OLD.name,
        OLD.duration_months,
        OLD.seats_total,
        OLD.seats_taken,
        OLD.description,
        CURRENT_TIMESTAMP
      );
    END;
    """

    # Execute backup tables + triggers
    with db.engine.connect() as conn:
        conn.execute(text(backup_applicant_sql))
        conn.execute(text(applicant_trigger_sql))
        conn.execute(text(backup_course_sql))
        conn.execute(text(course_trigger_sql))
        conn.commit()
        print("Backup tables and delete triggers created (deleted_applicants & deleted_courses).")

    # 5) Add demo data only if no courses exist
    if Course.query.count() == 0:
        c1 = Course(name='MCA - Computer Applications', duration_months=24, seats_total=60, description='Master of Computer Applications')
        c2 = Course(name='MSc - Data Science', duration_months=24, seats_total=30, description='MSc in Data Science')
        db.session.add_all([c1, c2])
        db.session.commit()

        a1 = Applicant(full_name='Alice Kumar', email='alice@example.com', phone='9998887776', dob='1999-05-23', course_id=c1.id, status='Applied')
        a2 = Applicant(full_name='Bob Roy', email='bob@example.com', phone='9990001112', dob='1998-11-11', course_id=c2.id, status='Shortlisted')
        db.session.add_all([a1, a2])
        db.session.commit()
        print('Demo data inserted.')

if __name__ == '__main__':
    # When running directly, allow creating DB from env or just run server
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'initdb':
        with app.app_context():
            init_db()
            print('Database initialized.')
    else:
        app.run(debug=True)
