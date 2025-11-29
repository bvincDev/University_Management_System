
-- Simple CRUD examples

-- CREATE (insert a new student)
-- Note: in production, store password hashes rather than plaintext.
INSERT INTO Student (first_name, last_name, email, password, birth_date, year, term, standing, major)
VALUES ('Test', 'Student', 'test.student@university.edu', 'tempPass!', '2004-09-01', 1, 'Fall', 'Freshman', 'Undeclared');

-- READ (select students enrolled in Computer Science with their enrollment info)
SELECT s.studentID, s.first_name, s.last_name, s.email, s.major,
       e.sectionID, e.grade, e.status
FROM Student s
LEFT JOIN Enrollment e ON s.studentID = e.studentID
WHERE s.major = 'Computer Science';

-- UPDATE (change a student's major)
UPDATE Student
SET major = 'Mathematics'
WHERE email = 'test.student@university.edu';

-- DELETE (cleanup the test student)
DELETE FROM Student
WHERE email = 'test.student@university.edu';

