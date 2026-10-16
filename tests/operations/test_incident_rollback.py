def test_incident_fences_existing_publication_without_provider_switch(tmp_path):
    from app.operations.drills import incident_rollback
    result = incident_rollback(tmp_path)
    assert result['optimization_disabled']
    assert result['affected_publication_stopped']
    assert not result['provider_switched']
    assert result['evidence_preserved']
    assert result['resume_requires_requalification']

