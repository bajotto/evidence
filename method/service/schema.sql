CREATE TABLE IF NOT EXISTS users (
    subject TEXT PRIMARY KEY,
    email TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$'),
    name TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(subject),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS project_memberships (
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    subject TEXT NOT NULL REFERENCES users(subject) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('owner', 'editor', 'reader')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, subject)
);

CREATE TABLE IF NOT EXISTS protocols (
    project_id UUID PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    revision BIGINT NOT NULL CHECK (revision > 0),
    updated_by TEXT NOT NULL REFERENCES users(subject),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS protocol_revisions (
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    revision BIGINT NOT NULL CHECK (revision > 0),
    content TEXT NOT NULL,
    actor_subject TEXT NOT NULL REFERENCES users(subject),
    summary TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, revision)
);

CREATE TABLE IF NOT EXISTS protocol_approvals (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    phase_number INTEGER NOT NULL CHECK (phase_number > 0),
    protocol_revision BIGINT NOT NULL,
    actor_subject TEXT NOT NULL REFERENCES users(subject),
    approved BOOLEAN NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (project_id, protocol_revision)
        REFERENCES protocol_revisions(project_id, revision)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    actor_subject TEXT NOT NULL REFERENCES users(subject),
    event_type TEXT NOT NULL,
    revision BIGINT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS audit_events_project_created_idx
    ON audit_events (project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS protocol_revisions_project_created_idx
    ON protocol_revisions (project_id, created_at DESC);

ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS disabled BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS join_key TEXT UNIQUE;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS phase_gate BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS gate_phase INTEGER;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS gate_phase_revision BIGINT;

CREATE TABLE IF NOT EXISTS user_tokens (
    id UUID PRIMARY KEY,
    subject TEXT NOT NULL REFERENCES users(subject) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS secret_categories (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE CHECK (name ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
    description TEXT NOT NULL DEFAULT ''
);

INSERT INTO secret_categories (name, description) VALUES
    ('credentials', 'Passwords and logins'),
    ('env', 'Environment information'),
    ('api-keys', 'API keys and tokens'),
    ('infra', 'Servers, hosts, certificates')
ON CONFLICT (name) DO NOTHING;

CREATE TABLE IF NOT EXISTS vault_secrets (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES secret_categories(id),
    name TEXT NOT NULL CHECK (name ~ '^[A-Za-z_][A-Za-z0-9_]{0,127}$'),
    nonce BYTEA NOT NULL,
    ciphertext BYTEA NOT NULL,
    key_version INTEGER NOT NULL DEFAULT 1,
    revision BIGINT NOT NULL DEFAULT 1,
    updated_by TEXT NOT NULL REFERENCES users(subject),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, name)
);

CREATE TABLE IF NOT EXISTS member_categories (
    project_id UUID NOT NULL,
    subject TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES secret_categories(id) ON DELETE CASCADE,
    PRIMARY KEY (project_id, subject, category_id),
    FOREIGN KEY (project_id, subject) REFERENCES project_memberships(project_id, subject) ON DELETE CASCADE
);

ALTER TABLE audit_events ALTER COLUMN project_id DROP NOT NULL;
ALTER TABLE vault_secrets ALTER COLUMN project_id DROP NOT NULL;
ALTER TABLE vault_secrets ADD COLUMN IF NOT EXISTS owner_subject TEXT REFERENCES users(subject);
ALTER TABLE vault_secrets DROP CONSTRAINT IF EXISTS vault_secrets_project_id_name_key;
CREATE UNIQUE INDEX IF NOT EXISTS vault_secrets_name_key ON vault_secrets (name);

CREATE TABLE IF NOT EXISTS secret_project_shares (
    secret_id UUID NOT NULL REFERENCES vault_secrets(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    PRIMARY KEY (secret_id, project_id)
);

-- A project can take every secret of a category from one owner, including secrets added later.
CREATE TABLE IF NOT EXISTS project_category_shares (
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES secret_categories(id) ON DELETE CASCADE,
    owner_subject TEXT NOT NULL REFERENCES users(subject) ON UPDATE CASCADE ON DELETE CASCADE,
    PRIMARY KEY (project_id, category_id, owner_subject)
);

-- Read side: which secrets a project holds, by explicit share or by category share.
CREATE OR REPLACE VIEW project_secret_scope AS
    SELECT secret_id, project_id FROM secret_project_shares
    UNION
    SELECT s.id, pc.project_id FROM project_category_shares pc
    JOIN vault_secrets s ON s.category_id = pc.category_id AND s.owner_subject = pc.owner_subject;

CREATE TABLE IF NOT EXISTS secret_user_shares (
    secret_id UUID NOT NULL REFERENCES vault_secrets(id) ON DELETE CASCADE,
    subject TEXT NOT NULL REFERENCES users(subject) ON DELETE CASCADE,
    PRIMARY KEY (secret_id, subject)
);

ALTER TABLE vault_secrets ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '';

ALTER TABLE user_tokens ADD COLUMN IF NOT EXISTS token_hint TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS protocol_reads (
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    subject TEXT NOT NULL REFERENCES users(subject) ON DELETE CASCADE,
    revision BIGINT NOT NULL,
    via TEXT NOT NULL,
    read_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, subject)
);
