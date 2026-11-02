"""Add missing performance indexes to all tables (v3.4.1)"""

MISSING_INDEXES = """
-- Performance indexes for frequently queried columns
CREATE INDEX IF NOT EXISTS idx_warns_user_id ON warns(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_created ON tickets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_polls_guild_created ON polls(guild_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_poll_votes_poll_user ON poll_votes(poll_id, user_id);
CREATE INDEX IF NOT EXISTS idx_giveaway_entries_user ON giveaway_entries(user_id);
CREATE INDEX IF NOT EXISTS idx_donations_user_id ON donations(user_id);
CREATE INDEX IF NOT EXISTS idx_donations_guild_created ON donations(guild_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_season_points_guild_user ON season_points(guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_reaction_roles_guild ON reaction_roles(guild_id);
CREATE INDEX IF NOT EXISTS idx_music_playlists_user ON music_playlists(user_id);
CREATE INDEX IF NOT EXISTS idx_music_history_user ON music_history(user_id);

-- Composite indexes for common queries
CREATE INDEX IF NOT EXISTS idx_moderation_cases_created ON moderation_cases(guild_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_audit_user ON admin_audit(role, timestamp DESC);
"""

async def apply_missing_indexes(db):
    """Apply all missing indexes to database"""
    for index_sql in MISSING_INDEXES.strip().split('\n'):
        if not index_sql.strip() or index_sql.startswith('--'):
            continue
        try:
            await db.execute(index_sql)
        except Exception as e:
            # Ignore if index already exists
            if "already exists" not in str(e).lower():
                raise
    await db.commit()
