-- 체스 기능 제거에 따른 운영 DB 정리 스크립트 (수동 실행 전용)
--
-- 서버는 더 이상 체스 테이블을 만들거나 읽지 않습니다. 이미 만들어진 테이블과 컬럼은
-- 남아 있어도 서비스에 영향이 없으므로, 아래 정리는 필수가 아닙니다.
-- 삭제는 되돌릴 수 없으니 실행 전에 반드시 백업하세요.
--
--   1) 백업:  pg_dump "$DATABASE_URL" -Fc -f backup_before_drop_chess.dump
--   2) 실행:  psql "$DATABASE_URL" -f migrations/manual/drop_chess.sql
--      (또는 pgAdmin4의 Query Tool에 붙여 넣어 실행)

BEGIN;

DROP TABLE IF EXISTS chess_game_chat_messages, chess_game_moves, chess_invites, chess_games CASCADE;

ALTER TABLE users
    DROP COLUMN IF EXISTS chess_rating,
    DROP COLUMN IF EXISTS chess_wins,
    DROP COLUMN IF EXISTS chess_draws,
    DROP COLUMN IF EXISTS chess_losses;

COMMIT;
