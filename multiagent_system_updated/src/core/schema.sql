PRAGMA foreign_keys = ON;

-- Tabela legada/compatível com o código atual
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
CREATE INDEX IF NOT EXISTS idx_agent_runs_history ON agent_runs(history_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_type ON agent_runs(agent_type);

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

-- View opcional para obter timestamps das últimas respostas por agente
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