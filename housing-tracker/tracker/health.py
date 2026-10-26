"""Collection heartbeat, separate from immutable market observations."""
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

FAILURE_STATUSES = {'blocked', 'cooldown', 'error', 'daily_budget_wait'}


def write_status(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def read_status(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def local_status_path(db):
    return Path(db).with_suffix('.collection-status.json')


def eastern(stamp):
    if not stamp:
        return '미확인'
    return datetime.fromisoformat(stamp.replace('Z', '+00:00')).astimezone(
        ZoneInfo('America/New_York')).strftime('%Y-%m-%d %I:%M %p %Z')


def status_notice(status, now=None):
    now = now or datetime.now(timezone.utc)
    kind = status.get('status')
    retry = status.get('retry_after')
    if kind in ('blocked', 'cooldown'):
        pending = bool(retry and datetime.fromisoformat(retry.replace('Z', '+00:00')) <= now)
        message = '수집 중단 · 접근 거부 후 대기 중'
        message += f" · 사유: {status.get('reason') or '원본 접근 제한'}"
        message += f" · 재시도 가능 시각: {eastern(retry)}"
        message += ' · 대기 시간이 지났으며 다음 배치 결과를 기다립니다.' if pending else ' · 이 시각 이후 첫 배치에서 재시도합니다.'
        return 'error', message
    if kind == 'error':
        return 'error', '수집 오류 · ' + (status.get('error') or status.get('reason') or '수집 실행 로그 확인 필요')
    if kind == 'daily_budget_wait':
        return 'warning', '수집 대기 · 오늘의 요청 한도 소진. 미국 동부시간 자정 이후 다음 배치에서 재시도합니다.'
    if kind == 'checkpointed':
        return 'warning', '수집 진행 중 · 일부 페이지만 저장됐으며 다음 배치에서 이어집니다.'
    if kind in ('idle', 'interval_wait'):
        return 'info', '이번 배치에는 새 원본 요청이 없습니다. 마지막 성공 시각을 확인하세요.'
    if kind == 'complete':
        return 'info', '최근 배치 수집 완료 · 학군별 마지막 성공 시각은 아래에 표시합니다.'
    return 'warning', '수집 실행 상태 미확인 · 저장된 마지막 성공 기록만 표시합니다.'


def status_stale(status, now=None):
    stamp = status.get('checked_at')
    if not stamp:
        return False
    now = now or datetime.now(timezone.utc)
    return (now - datetime.fromisoformat(stamp.replace('Z', '+00:00'))).total_seconds() > 7200
