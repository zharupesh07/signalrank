from api.models import GenerationQueue


def test_generation_queue_model_exists():
    assert GenerationQueue.__tablename__ == "generation_queue"
    assert hasattr(GenerationQueue, "user_id")
    assert hasattr(GenerationQueue, "job_id")
    assert hasattr(GenerationQueue, "status")
    assert hasattr(GenerationQueue, "error")
