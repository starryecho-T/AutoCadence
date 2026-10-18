from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ORIGINS = (
    'http://localhost:5173', 'http://127.0.0.1:5173',
    'http://localhost:3000', 'http://127.0.0.1:3000',
)

@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1] / 'runs')
    host: str = '127.0.0.1'
    port: int = 8765
    api_token: str | None = None
    cors_origins: tuple[str, ...] = DEFAULT_ORIGINS

    @classmethod
    def from_env(cls) -> 'Settings':
        defaults = cls()
        origins = os.getenv('VAI_CORS_ORIGINS')
        return cls(
            data_dir=Path(os.getenv('VAI_RUNS_DIR', str(defaults.data_dir))).expanduser().resolve(),
            host=os.getenv('VAI_HOST', defaults.host),
            port=int(os.getenv('VAI_PORT', str(defaults.port))),
            api_token=os.getenv('VAI_API_TOKEN') or None,
            cors_origins=tuple(x.strip() for x in origins.split(',') if x.strip()) if origins else DEFAULT_ORIGINS,
        )

    def validate_bind(self) -> None:
        if not self.api_token and self.host not in ('127.0.0.1', '::1', 'localhost'):
            raise ValueError('Set VAI_API_TOKEN before binding to a non-loopback host')
        if not 1 <= self.port <= 65535:
            raise ValueError('VAI_PORT must be between 1 and 65535')
        if '*' in self.cors_origins:
            raise ValueError('Use explicit VAI_CORS_ORIGINS; wildcard origins are not allowed')

def load_worker_config() -> dict:
    """Load local worker configuration without exposing its contents through HTTP."""
    path = Path(os.getenv('VAI_CONFIG', str(Path(__file__).resolve().parents[1] / 'config.local.json')))
    return json.loads(path.read_text(encoding='utf-8'))
