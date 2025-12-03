PRAGMA foreign_keys = ON;

-- Usuários para autenticação
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task TEXT NOT NULL,
    language TEXT,
    front_response TEXT,
    back_response TEXT,
    qa_response TEXT,
    created_at TEXT NOT NULL
);

-- Nova tabela normalizada: uma linha por execução de agente
CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    history_id INTEGER NOT NULL,
    agent_type TEXT NOT NULL CHECK (agent_type IN ('front','back','qa')),
    model TEXT,
    prompt TEXT,
    response TEXT NOT NULL,
    duration_ms INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (history_id) REFERENCES history(id) ON DELETE CASCADE
);

-- Índices úteis para consultas
CREATE INDEX IF NOT EXISTS idx_history_created_at ON history(created_at);
CREATE INDEX IF NOT EXISTS idx_history_user ON history(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_history ON agent_runs(history_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_type ON agent_runs(agent_type);

-- Eventos de autenticação (opcional, para auditoria e métricas)
CREATE TABLE IF NOT EXISTS auth_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    event_type TEXT NOT NULL CHECK (event_type IN ('register','login','logout','verify')),
    success INTEGER NOT NULL CHECK (success IN (0,1)) DEFAULT 1,
    ip TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_auth_events_user ON auth_events(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_events_type ON auth_events(event_type);
CREATE INDEX IF NOT EXISTS idx_auth_events_created ON auth_events(created_at);

-- Triggers para povoar agent_runs a partir de inserts na tabela history
CREATE TRIGGER IF NOT EXISTS trg_history_to_agent_front
AFTER INSERT ON history
WHEN NEW.front_response IS NOT NULL AND length(NEW.front_response) > 0
BEGIN
  INSERT INTO agent_runs (history_id, agent_type, response, created_at)
  VALUES (NEW.id, 'front', NEW.front_response, NEW.created_at);
END;

CREATE TRIGGER IF NOT EXISTS trg_history_to_agent_back
AFTER INSERT ON history
WHEN NEW.back_response IS NOT NULL AND length(NEW.back_response) > 0
BEGIN
  INSERT INTO agent_runs (history_id, agent_type, response, created_at)
  VALUES (NEW.id, 'back', NEW.back_response, NEW.created_at);
END;

CREATE TRIGGER IF NOT EXISTS trg_history_to_agent_qa
AFTER INSERT ON history
WHEN NEW.qa_response IS NOT NULL AND length(NEW.qa_response) > 0
BEGIN
  INSERT INTO agent_runs (history_id, agent_type, response, created_at)
  VALUES (NEW.id, 'qa', NEW.qa_response, NEW.created_at);
END;

-- Backfill de dados já existentes (executar muitas vezes é seguro)
INSERT INTO agent_runs (history_id, agent_type, response, created_at)
SELECT h.id, 'front', h.front_response, h.created_at
FROM history h
WHERE h.front_response IS NOT NULL AND length(h.front_response) > 0
  AND NOT EXISTS (
    SELECT 1 FROM agent_runs ar WHERE ar.history_id = h.id AND ar.agent_type = 'front'
  );

INSERT INTO agent_runs (history_id, agent_type, response, created_at)
SELECT h.id, 'back', h.back_response, h.created_at
FROM history h
WHERE h.back_response IS NOT NULL AND length(h.back_response) > 0
  AND NOT EXISTS (
    SELECT 1 FROM agent_runs ar WHERE ar.history_id = h.id AND ar.agent_type = 'back'
  );

INSERT INTO agent_runs (history_id, agent_type, response, created_at)
SELECT h.id, 'qa', h.qa_response, h.created_at
FROM history h
WHERE h.qa_response IS NOT NULL AND length(h.qa_response) > 0
  AND NOT EXISTS (
    SELECT 1 FROM agent_runs ar WHERE ar.history_id = h.id AND ar.agent_type = 'qa'
  );


CREATE VIEW IF NOT EXISTS v_history_latest AS
SELECT
  h.id,
  h.task,
  h.language,
  h.created_at,
  MAX(CASE WHEN ar.agent_type = 'front' THEN ar.created_at END) AS front_last_at,
  MAX(CASE WHEN ar.agent_type = 'back'  THEN ar.created_at END) AS back_last_at,
  MAX(CASE WHEN ar.agent_type = 'qa'    THEN ar.created_at END) AS qa_last_at
FROM history h
LEFT JOIN agent_runs ar ON ar.history_id = h.id
GROUP BY h.id;

-- View: atividades por usuário (contagem e último uso)
CREATE VIEW IF NOT EXISTS v_user_activity AS
SELECT
  u.id AS user_id,
  u.email,
  COUNT(h.id) AS runs_count,
  MAX(h.created_at) AS last_run_at
FROM users u
LEFT JOIN history h ON h.user_id = u.id
GROUP BY u.id, u.email;