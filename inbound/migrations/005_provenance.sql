CREATE TABLE attachment_locations (
    attachment_id INTEGER PRIMARY KEY REFERENCES attachments(id),
    locations_json TEXT NOT NULL
);
