from batch.context import SaaSContext, build_context, deep_merge, load_base_config


def test_deep_merge_overrides():
    base = {"a": 1, "b": {"c": 2, "d": 3}}
    over = {"b": {"c": 99}, "e": 5}
    result = deep_merge(base, over)
    assert result == {"a": 1, "b": {"c": 99, "d": 3}, "e": 5}


def test_deep_merge_no_mutation():
    base = {"a": {"b": 1}}
    over = {"a": {"c": 2}}
    deep_merge(base, over)
    assert base == {"a": {"b": 1}}


def test_load_base_config():
    cfg = load_base_config()
    assert "embeddings" in cfg
    assert "ranking" in cfg
    assert cfg["embeddings"]["embedding_dim"] == 384


def test_build_context():
    ctx = build_context(
        user_id="test-user",
        resume_text="I am a software engineer",
        config_overrides={"ranking": {"min_semantic_score": 0.60}},
    )
    assert isinstance(ctx, SaaSContext)
    assert ctx.user_id == "test-user"
    assert ctx.config["ranking"]["min_semantic_score"] == 0.60
    assert ctx.config["embeddings"]["embedding_dim"] == 384
    assert len(ctx.config_fp) == 32
