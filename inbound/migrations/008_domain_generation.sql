-- Authoritative content writes advance transactionally; runs and journal writes do not.
CREATE TRIGGER domain_messages_insert AFTER INSERT ON messages
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_messages_update AFTER UPDATE ON messages
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_messages_delete AFTER DELETE ON messages
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_message_history_insert AFTER INSERT ON message_history
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_message_history_update AFTER UPDATE ON message_history
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_message_history_delete AFTER DELETE ON message_history
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_attachments_insert AFTER INSERT ON attachments
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_attachments_update AFTER UPDATE ON attachments
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_attachments_delete AFTER DELETE ON attachments
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_triage_insert AFTER INSERT ON triage
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_triage_update AFTER UPDATE ON triage
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_triage_delete AFTER DELETE ON triage
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_message_extractions_insert AFTER INSERT ON message_extractions
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_message_extractions_update AFTER UPDATE ON message_extractions
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_message_extractions_delete AFTER DELETE ON message_extractions
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_opportunities_insert AFTER INSERT ON opportunities
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_opportunities_update AFTER UPDATE ON opportunities
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_opportunities_delete AFTER DELETE ON opportunities
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_opportunity_revisions_insert AFTER INSERT ON opportunity_revisions
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_opportunity_revisions_update AFTER UPDATE ON opportunity_revisions
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_opportunity_revisions_delete AFTER DELETE ON opportunity_revisions
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_fields_insert AFTER INSERT ON fields
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_fields_update AFTER UPDATE ON fields
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_fields_delete AFTER DELETE ON fields
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_roles_insert AFTER INSERT ON roles
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_roles_update AFTER UPDATE ON roles
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_roles_delete AFTER DELETE ON roles
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_merge_suggestions_insert AFTER INSERT ON merge_suggestions
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_merge_suggestions_update AFTER UPDATE ON merge_suggestions
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_merge_suggestions_delete AFTER DELETE ON merge_suggestions
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_packs_insert AFTER INSERT ON packs
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_packs_update AFTER UPDATE ON packs
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_packs_delete AFTER DELETE ON packs
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_attachment_locations_insert AFTER INSERT ON attachment_locations
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_attachment_locations_update AFTER UPDATE ON attachment_locations
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_attachment_locations_delete AFTER DELETE ON attachment_locations
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_attachment_recoveries_insert AFTER INSERT ON attachment_recoveries
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_attachment_recoveries_update AFTER UPDATE ON attachment_recoveries
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_attachment_recoveries_delete AFTER DELETE ON attachment_recoveries
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_snapshots_insert AFTER INSERT ON snapshots
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_snapshots_update AFTER UPDATE ON snapshots
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_snapshots_delete AFTER DELETE ON snapshots
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_category_history_insert AFTER INSERT ON category_history
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_category_history_update AFTER UPDATE ON category_history
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_category_history_delete AFTER DELETE ON category_history
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_review_events_insert AFTER INSERT ON review_events
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_review_events_update AFTER UPDATE ON review_events
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_review_events_delete AFTER DELETE ON review_events
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_evidence_projects_insert AFTER INSERT ON evidence_projects
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_evidence_projects_update AFTER UPDATE ON evidence_projects
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_evidence_projects_delete AFTER DELETE ON evidence_projects
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_evidence_bullets_insert AFTER INSERT ON evidence_bullets
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_evidence_bullets_update AFTER UPDATE ON evidence_bullets
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_evidence_bullets_delete AFTER DELETE ON evidence_bullets
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_skills_insert AFTER INSERT ON skills
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_skills_update AFTER UPDATE ON skills
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_skills_delete AFTER DELETE ON skills
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_skill_evidence_insert AFTER INSERT ON skill_evidence
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_skill_evidence_update AFTER UPDATE ON skill_evidence
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_skill_evidence_delete AFTER DELETE ON skill_evidence
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_evidence_snapshots_insert AFTER INSERT ON evidence_snapshots
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_evidence_snapshots_update AFTER UPDATE ON evidence_snapshots
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_evidence_snapshots_delete AFTER DELETE ON evidence_snapshots
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_settings_insert AFTER INSERT ON settings WHEN NEW.key<>'paused'
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_settings_update AFTER UPDATE ON settings WHEN NEW.key<>'paused' OR OLD.key<>'paused'
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_settings_delete AFTER DELETE ON settings WHEN OLD.key<>'paused'
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;

