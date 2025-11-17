from app import db, init_db, app

with app.app_context():
    init_db()
    print("DB initialized.")
with db.engine.connect() as conn:
    conn.execute("""
    CREATE TRIGGER IF NOT EXISTS update_course_seats
    AFTER UPDATE OF status ON applicants
    FOR EACH ROW
    WHEN NEW.status = 'Admitted'
    BEGIN
        UPDATE courses SET seats_taken = seats_taken + 1 WHERE id = NEW.course_id;
    END;
    """)  