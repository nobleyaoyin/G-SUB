-- Collaboration Base Schema v1: newly approved baseline; not historical pre-001.

-- Explicit base DDL; numbered migrations own their own objects and ledger.

PRAGMA foreign_keys=ON;

BEGIN IMMEDIATE;

CREATE TABLE collaboration_schema_version (version INTEGER PRIMARY KEY CHECK(version = 1), description TEXT NOT NULL);

INSERT INTO collaboration_schema_version (version, description) VALUES (1, 'Collaboration Base Schema v1');

CREATE TABLE users (
	user_id INTEGER NOT NULL,
	name VARCHAR(100) NOT NULL,
	email VARCHAR(255) NOT NULL,
	password_hash VARCHAR(255) NOT NULL,
	role VARCHAR(20) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (user_id)
);

CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE TABLE manuscripts (
	manuscript_id INTEGER NOT NULL,
	title VARCHAR(255) NOT NULL,
	abstract TEXT NOT NULL,
	author_id INTEGER NOT NULL,
	status VARCHAR(30) NOT NULL,
	review_round INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	file_path VARCHAR(500),
	PRIMARY KEY (manuscript_id),
	FOREIGN KEY(author_id) REFERENCES users (user_id)
);

CREATE TABLE eic_decisions (
	decision_id INTEGER NOT NULL,
	manuscript_id INTEGER NOT NULL,
	eic_id INTEGER NOT NULL,
	review_round INTEGER NOT NULL,
	decision VARCHAR(30) NOT NULL,
	comments TEXT NOT NULL,
	decided_at DATETIME NOT NULL,
	PRIMARY KEY (decision_id),
	FOREIGN KEY(manuscript_id) REFERENCES manuscripts (manuscript_id),
	FOREIGN KEY(eic_id) REFERENCES users (user_id)
);

CREATE INDEX ix_eic_decisions_decision_id ON eic_decisions (decision_id);

CREATE INDEX ix_eic_decisions_manuscript_id ON eic_decisions (manuscript_id);

CREATE TABLE eic_initial_scans (
	scan_id INTEGER NOT NULL,
	manuscript_id INTEGER NOT NULL,
	eic_id INTEGER NOT NULL,
	decision VARCHAR(30) NOT NULL,
	comments TEXT NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (scan_id),
	FOREIGN KEY(manuscript_id) REFERENCES manuscripts (manuscript_id),
	FOREIGN KEY(eic_id) REFERENCES users (user_id)
);

CREATE INDEX ix_eic_initial_scans_manuscript_id ON eic_initial_scans (manuscript_id);

CREATE TABLE final_editing_submissions (
	submission_id INTEGER NOT NULL,
	manuscript_id INTEGER NOT NULL,
	editor_id INTEGER NOT NULL,
	file_path VARCHAR(500) NOT NULL,
	comments TEXT NOT NULL,
	status VARCHAR(30) NOT NULL,
	author_comments TEXT,
	author_reviewed_at DATETIME,
	eic_comments TEXT,
	eic_reviewed_at DATETIME,
	eic_approved_by INTEGER,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (submission_id),
	FOREIGN KEY(manuscript_id) REFERENCES manuscripts (manuscript_id),
	FOREIGN KEY(editor_id) REFERENCES users (user_id),
	FOREIGN KEY(eic_approved_by) REFERENCES users (user_id)
);

CREATE INDEX ix_final_editing_submissions_editor_id ON final_editing_submissions (editor_id);

CREATE INDEX ix_final_editing_submissions_manuscript_id ON final_editing_submissions (manuscript_id);

CREATE INDEX ix_final_editing_submissions_submission_id ON final_editing_submissions (submission_id);

CREATE TABLE initial_editing_submissions (
	submission_id INTEGER NOT NULL,
	manuscript_id INTEGER NOT NULL,
	editor_id INTEGER NOT NULL,
	file_path VARCHAR(500) NOT NULL,
	comments TEXT NOT NULL,
	author_comments TEXT,
	editor_comments TEXT,
	editor_reviewed_at DATETIME,
	eic_comments TEXT,
	eic_reviewed_at DATETIME,
	eic_approved_by INTEGER,
	status VARCHAR(30) NOT NULL,
	created_at DATETIME NOT NULL,
	reviewed_at DATETIME,
	PRIMARY KEY (submission_id),
	FOREIGN KEY(manuscript_id) REFERENCES manuscripts (manuscript_id),
	FOREIGN KEY(editor_id) REFERENCES users (user_id),
	FOREIGN KEY(eic_approved_by) REFERENCES users (user_id)
);

CREATE INDEX ix_initial_editing_submissions_editor_id ON initial_editing_submissions (editor_id);

CREATE INDEX ix_initial_editing_submissions_manuscript_id ON initial_editing_submissions (manuscript_id);

CREATE TABLE initial_editor_invitations (
	invitation_id INTEGER NOT NULL,
	manuscript_id INTEGER NOT NULL,
	editor_id INTEGER NOT NULL,
	invited_by INTEGER NOT NULL,
	status VARCHAR(20) NOT NULL,
	invited_at DATETIME NOT NULL,
	responded_at DATETIME,
	PRIMARY KEY (invitation_id),
	FOREIGN KEY(manuscript_id) REFERENCES manuscripts (manuscript_id),
	FOREIGN KEY(editor_id) REFERENCES users (user_id),
	FOREIGN KEY(invited_by) REFERENCES users (user_id)
);

CREATE INDEX ix_initial_editor_invitations_editor_id ON initial_editor_invitations (editor_id);

CREATE INDEX ix_initial_editor_invitations_manuscript_id ON initial_editor_invitations (manuscript_id);

CREATE TABLE notifications (
	notification_id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	manuscript_id INTEGER,
	notification_type VARCHAR(50) NOT NULL,
	message TEXT NOT NULL,
	is_read BOOLEAN NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (notification_id),
	FOREIGN KEY(user_id) REFERENCES users (user_id),
	FOREIGN KEY(manuscript_id) REFERENCES manuscripts (manuscript_id)
);

CREATE INDEX ix_notifications_user_id ON notifications (user_id);

CREATE TABLE review_assignments (
	assignment_id INTEGER NOT NULL,
	manuscript_id INTEGER NOT NULL,
	reviewer_id INTEGER NOT NULL,
	assigned_by INTEGER NOT NULL,
	review_round INTEGER NOT NULL,
	status VARCHAR(30) NOT NULL,
	assigned_at DATETIME NOT NULL,
	PRIMARY KEY (assignment_id),
	FOREIGN KEY(manuscript_id) REFERENCES manuscripts (manuscript_id),
	FOREIGN KEY(reviewer_id) REFERENCES users (user_id),
	FOREIGN KEY(assigned_by) REFERENCES users (user_id)
);

CREATE TABLE pre_review_confirmations (
	confirmation_id INTEGER NOT NULL,
	manuscript_id INTEGER NOT NULL,
	submission_id INTEGER NOT NULL,
	author_id INTEGER NOT NULL,
	file_path VARCHAR NOT NULL,
	decision VARCHAR NOT NULL,
	comments TEXT NOT NULL,
	confirmed_at DATETIME NOT NULL,
	PRIMARY KEY (confirmation_id),
	FOREIGN KEY(manuscript_id) REFERENCES manuscripts (manuscript_id),
	FOREIGN KEY(submission_id) REFERENCES initial_editing_submissions (submission_id),
	FOREIGN KEY(author_id) REFERENCES users (user_id)
);

CREATE INDEX ix_pre_review_confirmations_confirmation_id ON pre_review_confirmations (confirmation_id);

CREATE INDEX ix_pre_review_confirmations_manuscript_id ON pre_review_confirmations (manuscript_id);

CREATE INDEX ix_pre_review_confirmations_submission_id ON pre_review_confirmations (submission_id);

CREATE TABLE reviews (
	review_id INTEGER NOT NULL,
	assignment_id INTEGER NOT NULL,
	comments TEXT NOT NULL,
	recommendation VARCHAR(30) NOT NULL,
	submitted_at DATETIME NOT NULL,
	PRIMARY KEY (review_id),
	UNIQUE (assignment_id),
	FOREIGN KEY(assignment_id) REFERENCES review_assignments (assignment_id)
);

COMMIT;
