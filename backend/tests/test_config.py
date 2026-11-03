from app import config


def _fresh_settings(monkeypatch, profile: str):
    """프로필을 바꿔 Settings 를 새로 생성 (환경변수 간섭 제거)."""
    monkeypatch.setattr(config, "PROFILE", profile)
    monkeypatch.delenv("DB_BACKEND", raising=False)  # conftest 가 넣은 값 제거
    return config.Settings()


def test_local_profile_uses_duckdb(monkeypatch):
    s = _fresh_settings(monkeypatch, "local")
    assert s.db_backend == "duckdb"


def test_prod_profile_overrides_to_oracle(monkeypatch):
    s = _fresh_settings(monkeypatch, "prod")
    assert s.db_backend == "oracle"
    assert s.oracle_schema == "SALES"


def test_missing_profile_file_falls_back_to_base(monkeypatch):
    # application-staging.yml 은 없음 → 공통 application.yml 값 적용
    s = _fresh_settings(monkeypatch, "staging")
    assert s.db_backend == "duckdb"


def test_env_var_beats_profile_yaml(monkeypatch):
    # 환경변수가 프로필 yml 보다 우선 (k8s Secret/ConfigMap 주입 시나리오)
    monkeypatch.setattr(config, "PROFILE", "prod")
    monkeypatch.setenv("DB_BACKEND", "duckdb")
    s = config.Settings()
    assert s.db_backend == "duckdb"
