from modeler_contracts.runs import derive_chunk_seed


def test_chunk_seeds_are_deterministic_distinct_and_int32():
    seeds = [derive_chunk_seed(42, i) for i in range(1000)]
    assert seeds == [derive_chunk_seed(42, i) for i in range(1000)]
    assert len(set(seeds)) == len(seeds)
    assert all(0 <= s <= 2**31 - 1 for s in seeds)
    assert derive_chunk_seed(43, 0) != derive_chunk_seed(42, 0)
