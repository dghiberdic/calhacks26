from world.generator import generate_world


def test_natural_corpus_contains_unobservable_ambiguity_in_both_splits():
    generated = generate_world(seed=0)
    for split in ("train", "test"):
        cancelled = [t for t in generated.truth.flights.values()
                     if t.status == "cancelled" and t.split == split and not t.golden]
        ambiguous = [t for t in cancelled if t.ambiguous]
        assert 0.02 <= len(ambiguous) / len(cancelled) <= 0.10
        assert all(t.latent == "crew" and t.ops_code in {"71", "72"} for t in ambiguous)
        assert all(t.extraordinary == "not_extraordinary" for t in ambiguous)
