"""SQLite DDL compatible with Fizzy's db/schema_sqlite.rb (Rails 8).

UUID columns are blobs. A database produced by the Ruby app is opened as-is.
This DDL runs only when the file has no `accounts` table yet. An older
`reactions` table, from before reactions became polymorphic, is migrated in
place to the current columns.
"""

from __future__ import annotations

SCHEMA_VERSION = "20260828120000"
REACTIONS_POLYMORPHIC_VERSION = "20260121155752"

# (name, declared type, sql suffix or None)
# pk columns are omitted here; tables with an id get a blob primary key.

def _tables() -> list[tuple[str, list[tuple[str, str, str | None]], list[tuple[str, str, bool]]]]:
    u = "blob"
    dt = "datetime(6)"
    s = "varchar(255)"
    su = "varchar"
    t = "text"
    i = "integer"
    bi = "bigint"
    b = "boolean"
    j = "json"
    d = "date"

    def nn(default=None):
        if default is None:
            return "NOT NULL"
        return f"DEFAULT {default} NOT NULL"

    tables = []

    def add(name, cols, indexes=(), ident=True):
        tables.append((name, cols, indexes, ident))

    add("accesses", [
        ("accessed_at", dt, None),
        ("account_id", u, nn()),
        ("board_id", u, nn()),
        ("created_at", dt, nn()),
        ("involvement", s, "DEFAULT 'access_only' NOT NULL"),
        ("updated_at", dt, nn()),
        ("user_id", u, nn()),
    ], [
        ("index_accesses_on_account_id_and_accessed_at", "account_id, accessed_at", False),
        ("index_accesses_on_board_id_and_user_id", "board_id, user_id", True),
        ("index_accesses_on_board_id", "board_id", False),
        ("index_accesses_on_user_id", "user_id", False),
    ])
    add("account_cancellations", [
        ("account_id", u, nn()),
        ("created_at", dt, nn()),
        ("initiated_by_id", u, nn()),
        ("updated_at", dt, nn()),
    ], [("index_account_cancellations_on_account_id", "account_id", True)])
    add("account_external_id_sequences", [
        ("value", bi, nn(0)),
    ], [("index_account_external_id_sequences_on_value", "value", True)])
    add("account_imports", [
        ("account_id", u, None),
        ("completed_at", dt, None),
        ("created_at", dt, nn()),
        ("failure_reason", s, None),
        ("identity_id", u, nn()),
        ("status", s, "DEFAULT 'pending' NOT NULL"),
        ("updated_at", dt, nn()),
    ], [
        ("index_account_imports_on_account_id", "account_id", False),
        ("index_account_imports_on_identity_id", "identity_id", False),
    ])
    add("account_join_codes", [
        ("account_id", u, nn()),
        ("code", s, nn()),
        ("created_at", dt, nn()),
        ("updated_at", dt, nn()),
        ("usage_count", bi, nn(0)),
        ("usage_limit", bi, nn(10)),
    ], [("index_account_join_codes_on_account_id_and_code", "account_id, code", True)])
    add("accounts", [
        ("cards_count", bi, nn(0)),
        ("created_at", dt, nn()),
        ("external_account_id", bi, None),
        ("name", s, nn()),
        ("updated_at", dt, nn()),
    ], [("index_accounts_on_external_account_id", "external_account_id", True)])
    add("action_pack_passkeys", [
        ("aaguid", s, None),
        ("backed_up", b, None),
        ("created_at", dt, nn()),
        ("credential_id", s, nn()),
        ("holder_id", u, nn()),
        ("holder_type", s, nn()),
        ("name", s, None),
        ("public_key", "blob", nn()),
        ("sign_count", bi, nn(0)),
        ("transports", t, None),
        ("updated_at", dt, nn()),
    ], [
        ("index_action_pack_passkeys_on_credential_id", "credential_id", True),
        ("index_action_pack_passkeys_on_holder_type_and_holder_id", "holder_type, holder_id", False),
    ])
    add("action_text_rich_texts", [
        ("account_id", u, nn()),
        ("body", t, None),
        ("created_at", dt, nn()),
        ("name", s, nn()),
        ("record_id", u, nn()),
        ("record_type", s, nn()),
        ("updated_at", dt, nn()),
    ], [
        ("index_action_text_rich_texts_on_account_id", "account_id", False),
        ("index_action_text_rich_texts_uniqueness", "record_type, record_id, name", True),
    ])
    add("active_storage_attachments", [
        ("account_id", u, nn()),
        ("blob_id", u, nn()),
        ("created_at", dt, nn()),
        ("name", s, nn()),
        ("record_id", u, nn()),
        ("record_type", s, nn()),
    ], [
        ("index_active_storage_attachments_on_account_id", "account_id", False),
        ("index_active_storage_attachments_on_blob_id", "blob_id", False),
        ("index_active_storage_attachments_uniqueness", "record_type, record_id, name, blob_id", True),
    ])
    add("active_storage_blobs", [
        ("account_id", u, nn()),
        ("byte_size", bi, nn()),
        ("checksum", s, None),
        ("content_type", s, None),
        ("created_at", dt, nn()),
        ("filename", s, nn()),
        ("key", s, nn()),
        ("metadata", t, None),
        ("service_name", s, nn()),
    ], [
        ("index_active_storage_blobs_on_account_id", "account_id", False),
        ("index_active_storage_blobs_on_key", "key", True),
    ])
    add("active_storage_variant_records", [
        ("account_id", u, nn()),
        ("blob_id", u, nn()),
        ("variation_digest", s, nn()),
    ], [
        ("index_active_storage_variant_records_on_account_id", "account_id", False),
        ("index_active_storage_variant_records_uniqueness", "blob_id, variation_digest", True),
    ])
    add("assignees_filters", [
        ("assignee_id", u, nn()),
        ("filter_id", u, nn()),
    ], [
        ("index_assignees_filters_on_assignee_id", "assignee_id", False),
        ("index_assignees_filters_on_filter_id", "filter_id", False),
    ], ident=False)
    add("assigners_filters", [
        ("assigner_id", u, nn()),
        ("filter_id", u, nn()),
    ], [
        ("index_assigners_filters_on_assigner_id", "assigner_id", False),
        ("index_assigners_filters_on_filter_id", "filter_id", False),
    ], ident=False)
    add("assignments", [
        ("account_id", u, nn()),
        ("assignee_id", u, nn()),
        ("assigner_id", u, nn()),
        ("card_id", u, nn()),
        ("created_at", dt, nn()),
        ("updated_at", dt, nn()),
    ], [
        ("index_assignments_on_account_id", "account_id", False),
        ("index_assignments_on_assignee_id_and_card_id", "assignee_id, card_id", True),
        ("index_assignments_on_card_id", "card_id", False),
    ])
    add("board_publications", [
        ("account_id", u, nn()),
        ("board_id", u, nn()),
        ("created_at", dt, nn()),
        ("key", s, None),
        ("updated_at", dt, nn()),
    ], [
        ("index_board_publications_on_account_id", "account_id", False),
        ("index_board_publications_on_board_id", "board_id", False),
        ("index_board_publications_on_key", "key", True),
    ])
    add("boards", [
        ("account_id", u, nn()),
        ("all_access", b, "DEFAULT 0 NOT NULL"),
        ("created_at", dt, nn()),
        ("creator_id", u, nn()),
        ("name", s, nn()),
        ("updated_at", dt, nn()),
    ], [
        ("index_boards_on_account_id", "account_id", False),
        ("index_boards_on_creator_id", "creator_id", False),
    ])
    add("boards_filters", [
        ("board_id", u, nn()),
        ("filter_id", u, nn()),
    ], [
        ("index_boards_filters_on_board_id", "board_id", False),
        ("index_boards_filters_on_filter_id", "filter_id", False),
    ], ident=False)
    add("card_activity_spikes", [
        ("account_id", u, nn()),
        ("card_id", u, nn()),
        ("created_at", dt, nn()),
        ("updated_at", dt, nn()),
    ], [
        ("index_card_activity_spikes_on_account_id", "account_id", False),
        ("index_card_activity_spikes_on_card_id", "card_id", True),
    ])
    add("card_goldnesses", [
        ("account_id", u, nn()),
        ("card_id", u, nn()),
        ("created_at", dt, nn()),
        ("updated_at", dt, nn()),
    ], [
        ("index_card_goldnesses_on_account_id", "account_id", False),
        ("index_card_goldnesses_on_card_id", "card_id", True),
    ])
    add("card_not_nows", [
        ("account_id", u, nn()),
        ("card_id", u, nn()),
        ("created_at", dt, nn()),
        ("updated_at", dt, nn()),
        ("user_id", u, None),
    ], [
        ("index_card_not_nows_on_account_id", "account_id", False),
        ("index_card_not_nows_on_card_id", "card_id", True),
        ("index_card_not_nows_on_user_id", "user_id", False),
    ])
    add("cards", [
        ("account_id", u, nn()),
        ("board_id", u, nn()),
        ("column_id", u, None),
        ("created_at", dt, nn()),
        ("creator_id", u, nn()),
        ("due_on", d, None),
        ("last_active_at", dt, nn()),
        ("number", bi, nn()),
        ("status", s, "DEFAULT 'drafted' NOT NULL"),
        ("title", s, None),
        ("updated_at", dt, nn()),
    ], [
        ("index_cards_on_account_id_and_board_id_and_status", "account_id, board_id, status", False),
        ("index_cards_on_account_id_and_last_active_at_and_status", "account_id, last_active_at, status", False),
        ("index_cards_on_account_id_and_number", "account_id, number", True),
        ("index_cards_on_board_id", "board_id", False),
        ("index_cards_on_column_id", "column_id", False),
    ])
    add("closers_filters", [
        ("closer_id", u, nn()),
        ("filter_id", u, nn()),
    ], [
        ("index_closers_filters_on_closer_id", "closer_id", False),
        ("index_closers_filters_on_filter_id", "filter_id", False),
    ], ident=False)
    add("closures", [
        ("account_id", u, nn()),
        ("card_id", u, nn()),
        ("created_at", dt, nn()),
        ("updated_at", dt, nn()),
        ("user_id", u, None),
    ], [
        ("index_closures_on_account_id", "account_id", False),
        ("index_closures_on_card_id_and_created_at", "card_id, created_at", False),
        ("index_closures_on_card_id", "card_id", True),
        ("index_closures_on_user_id", "user_id", False),
    ])
    add("columns", [
        ("account_id", u, nn()),
        ("board_id", u, nn()),
        ("color", s, nn()),
        ("created_at", dt, nn()),
        ("name", s, nn()),
        ("position", i, nn(0)),
        ("updated_at", dt, nn()),
    ], [
        ("index_columns_on_account_id", "account_id", False),
        ("index_columns_on_board_id_and_position", "board_id, position", False),
        ("index_columns_on_board_id", "board_id", False),
    ])
    add("comments", [
        ("account_id", u, nn()),
        ("card_id", u, nn()),
        ("created_at", dt, nn()),
        ("creator_id", u, nn()),
        ("updated_at", dt, nn()),
    ], [
        ("index_comments_on_account_id", "account_id", False),
        ("index_comments_on_card_id", "card_id", False),
    ])
    add("creators_filters", [
        ("creator_id", u, nn()),
        ("filter_id", u, nn()),
    ], [
        ("index_creators_filters_on_creator_id", "creator_id", False),
        ("index_creators_filters_on_filter_id", "filter_id", False),
    ], ident=False)
    add("entropies", [
        ("account_id", u, nn()),
        ("auto_postpone_period", bi, nn(2592000)),
        ("container_id", u, nn()),
        ("container_type", s, nn()),
        ("created_at", dt, nn()),
        ("updated_at", dt, nn()),
    ], [
        ("index_entropies_on_account_id", "account_id", False),
        ("idx_on_container_type_container_id_auto_postpone_pe_3d79b50517", "container_type, container_id, auto_postpone_period", False),
        ("index_entropy_configurations_on_container", "container_type, container_id", True),
    ])
    add("events", [
        ("account_id", u, nn()),
        ("action", s, nn()),
        ("board_id", u, nn()),
        ("created_at", dt, nn()),
        ("creator_id", u, nn()),
        ("eventable_id", u, nn()),
        ("eventable_type", s, nn()),
        ("particulars", j, "DEFAULT (json_object())"),
        ("updated_at", dt, nn()),
    ], [
        ("index_events_on_account_id_and_action", "account_id, action", False),
        ("index_events_on_board_id_and_action_and_created_at", "board_id, action, created_at", False),
        ("index_events_on_board_id", "board_id", False),
        ("index_events_on_creator_id", "creator_id", False),
        ("index_events_on_eventable", "eventable_type, eventable_id", False),
    ])
    add("exports", [
        ("account_id", u, nn()),
        ("completed_at", dt, None),
        ("created_at", dt, nn()),
        ("status", s, "DEFAULT 'pending' NOT NULL"),
        ("type", s, None),
        ("updated_at", dt, nn()),
        ("user_id", u, nn()),
    ], [
        ("index_exports_on_account_id", "account_id", False),
        ("index_exports_on_type", "type", False),
        ("index_exports_on_user_id", "user_id", False),
    ])
    add("filters", [
        ("account_id", u, nn()),
        ("created_at", dt, nn()),
        ("creator_id", u, nn()),
        ("fields", j, "DEFAULT (json_object()) NOT NULL"),
        ("params_digest", s, nn()),
        ("updated_at", dt, nn()),
    ], [
        ("index_filters_on_account_id", "account_id", False),
        ("index_filters_on_creator_id_and_params_digest", "creator_id, params_digest", True),
    ])
    add("filters_tags", [
        ("filter_id", u, nn()),
        ("tag_id", u, nn()),
    ], [
        ("index_filters_tags_on_filter_id", "filter_id", False),
        ("index_filters_tags_on_tag_id", "tag_id", False),
    ], ident=False)
    add("identities", [
        ("created_at", dt, nn()),
        ("email_address", su, nn()),
        ("staff", b, "DEFAULT 0 NOT NULL"),
        ("updated_at", dt, nn()),
    ], [("index_identities_on_email_address", "email_address", True)])
    add("identity_access_tokens", [
        ("created_at", dt, nn()),
        ("description", t, None),
        ("identity_id", u, nn()),
        ("permission", s, None),
        ("token", s, None),
        ("updated_at", dt, nn()),
    ], [("index_access_token_on_identity_id", "identity_id", False)])
    add("identity_transfers", [
        ("created_at", dt, nn()),
        ("identity_id", u, nn()),
        ("token", s, nn()),
        ("updated_at", dt, nn()),
    ], [
        ("index_identity_transfers_on_identity_id", "identity_id", False),
        ("index_identity_transfers_on_token", "token", True),
    ])
    add("magic_links", [
        ("code", s, nn()),
        ("created_at", dt, nn()),
        ("expires_at", dt, nn()),
        ("identity_id", u, None),
        ("purpose", i, nn()),
        ("updated_at", dt, nn()),
    ], [
        ("index_magic_links_on_code", "code", True),
        ("index_magic_links_on_expires_at", "expires_at", False),
        ("index_magic_links_on_identity_id", "identity_id", False),
    ])
    add("mentions", [
        ("account_id", u, nn()),
        ("created_at", dt, nn()),
        ("mentionee_id", u, nn()),
        ("mentioner_id", u, nn()),
        ("source_id", u, nn()),
        ("source_type", s, nn()),
        ("updated_at", dt, nn()),
    ], [
        ("index_mentions_on_account_id", "account_id", False),
        ("index_mentions_on_mentionee_id", "mentionee_id", False),
        ("index_mentions_on_mentioner_id", "mentioner_id", False),
        ("index_mentions_on_source", "source_type, source_id", False),
    ])
    add("notification_bundles", [
        ("account_id", u, nn()),
        ("created_at", dt, nn()),
        ("ends_at", dt, nn()),
        ("starts_at", dt, nn()),
        ("status", i, nn(0)),
        ("updated_at", dt, nn()),
        ("user_id", u, nn()),
    ], [
        ("index_notification_bundles_on_account_id", "account_id", False),
        ("index_notification_bundles_on_ends_at_and_status", "ends_at, status", False),
        ("idx_on_user_id_starts_at_ends_at_7eae5d3ac5", "user_id, starts_at, ends_at", False),
        ("index_notification_bundles_on_user_id_and_status", "user_id, status", False),
    ])
    add("notifications", [
        ("account_id", u, nn()),
        ("card_id", u, nn()),
        ("created_at", dt, nn()),
        ("creator_id", u, None),
        ("read_at", dt, None),
        ("source_id", u, nn()),
        ("source_type", s, nn()),
        ("unread_count", i, nn(0)),
        ("updated_at", dt, nn()),
        ("user_id", u, nn()),
    ], [
        ("index_notifications_on_account_id", "account_id", False),
        ("index_notifications_on_creator_id", "creator_id", False),
        ("index_notifications_on_source", "source_type, source_id", False),
        ("index_notifications_on_user_id_and_card_id", "user_id, card_id", True),
        ("index_notifications_on_user_id_and_read_at_and_updated_at", "user_id, read_at DESC, updated_at DESC", False),
        ("index_notifications_on_user_id", "user_id", False),
    ])
    add("pins", [
        ("account_id", u, nn()),
        ("card_id", u, nn()),
        ("created_at", dt, nn()),
        ("updated_at", dt, nn()),
        ("user_id", u, nn()),
    ], [
        ("index_pins_on_account_id", "account_id", False),
        ("index_pins_on_card_id_and_user_id", "card_id, user_id", True),
        ("index_pins_on_card_id", "card_id", False),
        ("index_pins_on_user_id", "user_id", False),
    ])
    add("push_subscriptions", [
        ("account_id", u, nn()),
        ("auth_key", s, None),
        ("created_at", dt, nn()),
        ("endpoint", t, None),
        ("p256dh_key", s, None),
        ("updated_at", dt, nn()),
        ("user_agent", "varchar(4096)", None),
        ("user_id", u, nn()),
    ], [
        ("index_push_subscriptions_on_account_id", "account_id", False),
        ("index_push_subscriptions_on_user_id_and_endpoint", "user_id, endpoint", True),
    ])
    add("reactions", [
        ("account_id", u, nn()),
        ("content", "varchar(16)", nn()),
        ("created_at", dt, nn()),
        ("reactable_id", u, nn()),
        ("reactable_type", s, nn()),
        ("reacter_id", u, nn()),
        ("updated_at", dt, nn()),
    ], [
        ("index_reactions_on_account_id", "account_id", False),
        ("index_reactions_on_reactable_type_and_reactable_id", "reactable_type, reactable_id", False),
        ("index_reactions_on_reacter_id", "reacter_id", False),
    ])
    add("search_records", [
        ("id", i, "PRIMARY KEY"),
        ("account_id", u, nn()),
        ("board_id", u, nn()),
        ("card_id", u, nn()),
        ("content", t, None),
        ("created_at", dt, nn()),
        ("searchable_id", u, nn()),
        ("searchable_type", s, nn()),
        ("title", s, None),
    ], [
        ("index_search_records_on_account_id", "account_id", False),
        ("index_search_records_on_searchable_type_and_searchable_id", "searchable_type, searchable_id", True),
    ], ident=False)
    add("search_queries", [
        ("account_id", u, nn()),
        ("created_at", dt, nn()),
        ("terms", "varchar(2000)", nn()),
        ("updated_at", dt, nn()),
        ("user_id", u, nn()),
    ], [
        ("index_search_queries_on_account_id", "account_id", False),
        ("index_search_queries_on_user_id_and_terms", "user_id, terms", False),
        ("index_search_queries_on_user_id_and_updated_at", "user_id, updated_at", True),
        ("index_search_queries_on_user_id", "user_id", False),
    ])
    add("sessions", [
        ("created_at", dt, nn()),
        ("identity_id", u, nn()),
        ("ip_address", s, None),
        ("updated_at", dt, nn()),
        ("user_agent", "varchar(4096)", None),
    ], [("index_sessions_on_identity_id", "identity_id", False)])
    add("steps", [
        ("account_id", u, nn()),
        ("card_id", u, nn()),
        ("completed", b, "DEFAULT 0 NOT NULL"),
        ("content", t, nn()),
        ("created_at", dt, nn()),
        ("updated_at", dt, nn()),
    ], [
        ("index_steps_on_account_id", "account_id", False),
        ("index_steps_on_card_id_and_completed", "card_id, completed", False),
        ("index_steps_on_card_id", "card_id", False),
    ])
    add("storage_entries", [
        ("account_id", u, nn()),
        ("blob_id", u, None),
        ("board_id", u, None),
        ("created_at", dt, nn()),
        ("delta", bi, nn()),
        ("operation", s, nn()),
        ("recordable_id", u, None),
        ("recordable_type", s, None),
        ("request_id", s, None),
        ("user_id", u, None),
    ], [
        ("index_storage_entries_on_account_id", "account_id", False),
        ("index_storage_entries_on_blob_id", "blob_id", False),
        ("index_storage_entries_on_board_id", "board_id", False),
        ("index_storage_entries_on_recordable", "recordable_type, recordable_id", False),
        ("index_storage_entries_on_request_id", "request_id", False),
        ("index_storage_entries_on_user_id", "user_id", False),
    ])
    add("storage_totals", [
        ("bytes_stored", bi, nn(0)),
        ("created_at", dt, nn()),
        ("last_entry_id", u, None),
        ("owner_id", u, nn()),
        ("owner_type", s, nn()),
        ("updated_at", dt, nn()),
    ], [("index_storage_totals_on_owner_type_and_owner_id", "owner_type, owner_id", True)])
    add("taggings", [
        ("account_id", u, nn()),
        ("card_id", u, nn()),
        ("created_at", dt, nn()),
        ("tag_id", u, nn()),
        ("updated_at", dt, nn()),
    ], [
        ("index_taggings_on_account_id", "account_id", False),
        ("index_taggings_on_card_id_and_tag_id", "card_id, tag_id", True),
        ("index_taggings_on_tag_id", "tag_id", False),
    ])
    add("tags", [
        ("account_id", u, nn()),
        ("created_at", dt, nn()),
        ("title", s, None),
        ("updated_at", dt, nn()),
    ], [("index_tags_on_account_id_and_title", "account_id, title", True)])
    add("user_settings", [
        ("account_id", u, nn()),
        ("bundle_email_frequency", i, nn(0)),
        ("created_at", dt, nn()),
        ("timezone_name", s, None),
        ("updated_at", dt, nn()),
        ("user_id", u, nn()),
    ], [
        ("index_user_settings_on_account_id", "account_id", False),
        ("index_user_settings_on_user_id_and_bundle_email_frequency", "user_id, bundle_email_frequency", False),
        ("index_user_settings_on_user_id", "user_id", False),
    ])
    add("users", [
        ("account_id", u, nn()),
        ("active", b, "DEFAULT 1 NOT NULL"),
        ("created_at", dt, nn()),
        ("identity_id", u, None),
        ("name", s, nn()),
        ("role", s, "DEFAULT 'member' NOT NULL"),
        ("updated_at", dt, nn()),
        ("verified_at", dt, None),
    ], [
        ("index_users_on_account_id_and_identity_id", "account_id, identity_id", True),
        ("index_users_on_account_id_and_role", "account_id, role", False),
        ("index_users_on_identity_id", "identity_id", False),
    ])
    add("watches", [
        ("account_id", u, nn()),
        ("card_id", u, nn()),
        ("created_at", dt, nn()),
        ("updated_at", dt, nn()),
        ("user_id", u, nn()),
        ("watching", b, "DEFAULT 1 NOT NULL"),
    ], [
        ("index_watches_on_account_id", "account_id", False),
        ("index_watches_on_card_id", "card_id", False),
        ("index_watches_on_user_id_and_card_id", "user_id, card_id", False),
        ("index_watches_on_user_id", "user_id", False),
    ])
    add("webhook_delinquency_trackers", [
        ("account_id", u, nn()),
        ("consecutive_failures_count", i, "DEFAULT 0"),
        ("created_at", dt, nn()),
        ("first_failure_at", dt, None),
        ("updated_at", dt, nn()),
        ("webhook_id", u, nn()),
    ], [
        ("index_webhook_delinquency_trackers_on_account_id", "account_id", False),
        ("index_webhook_delinquency_trackers_on_webhook_id", "webhook_id", False),
    ])
    add("webhook_deliveries", [
        ("account_id", u, nn()),
        ("created_at", dt, nn()),
        ("event_id", u, nn()),
        ("request", t, None),
        ("response", t, None),
        ("state", s, nn()),
        ("updated_at", dt, nn()),
        ("webhook_id", u, nn()),
    ], [
        ("index_webhook_deliveries_on_account_id", "account_id", False),
        ("index_webhook_deliveries_on_created_at", "created_at", False),
        ("index_webhook_deliveries_on_event_id", "event_id", False),
        ("index_webhook_deliveries_on_webhook_id", "webhook_id", False),
    ])
    add("webhooks", [
        ("account_id", u, nn()),
        ("active", b, "DEFAULT 1 NOT NULL"),
        ("board_id", u, nn()),
        ("created_at", dt, nn()),
        ("name", s, None),
        ("signing_secret", s, nn()),
        ("subscribed_actions", t, None),
        ("updated_at", dt, nn()),
        ("url", t, nn()),
    ], [
        ("index_webhooks_on_account_id", "account_id", False),
        ("index_webhooks_on_board_id_and_subscribed_actions", "board_id, subscribed_actions", False),
    ])
    return tables


def statements() -> list[str]:
    sql = [
        'CREATE TABLE IF NOT EXISTS "schema_migrations" ("version" varchar NOT NULL PRIMARY KEY)',
        'CREATE TABLE IF NOT EXISTS "ar_internal_metadata" ('
        '"key" varchar NOT NULL PRIMARY KEY, "value" varchar, '
        '"created_at" datetime(6) NOT NULL, "updated_at" datetime(6) NOT NULL)',
    ]
    for name, cols, indexes, ident in _tables():
        parts = []
        if ident:
            parts.append('"id" blob NOT NULL PRIMARY KEY')
        for col_name, declared, suffix in cols:
            piece = f'"{col_name}" {declared}'
            if suffix:
                piece += f" {suffix}"
            parts.append(piece)
        sql.append(f'CREATE TABLE IF NOT EXISTS "{name}" ({", ".join(parts)})')
        for index_name, columns, unique in indexes:
            kind = "UNIQUE INDEX" if unique else "INDEX"
            sql.append(f'CREATE {kind} IF NOT EXISTS "{index_name}" ON "{name}" ({columns})')
    sql.append(
        "CREATE VIRTUAL TABLE IF NOT EXISTS search_records_fts USING fts5("
        "title, content, tokenize='porter')"
    )
    return sql


def _column_names(conn, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}


def _migrate_reactions(conn) -> None:
    """Port of db/migrate/20260121155752_make_reactions_polymorphic.rb.

    Older files store a reaction on comment_id. The current table stores
    reactable_type and reactable_id, and comment_id is gone.
    """
    columns = _column_names(conn, "reactions")
    if not columns or ("reactable_type" in columns and "comment_id" not in columns):
        return
    if "comment_id" not in columns:
        return
    account_sql = "COALESCE(old.account_id, comments.account_id)" if "account_id" in columns else "comments.account_id"
    reactable_id_sql = "COALESCE(old.reactable_id, old.comment_id)" if "reactable_id" in columns else "old.comment_id"
    reactable_type_sql = "COALESCE(old.reactable_type, 'Comment')" if "reactable_type" in columns else "'Comment'"
    missing = conn.execute(
        f"""
        SELECT COUNT(*) AS n FROM reactions AS old
        LEFT JOIN comments ON comments.id = old.comment_id
        WHERE {account_sql} IS NULL
        """
    ).fetchone()["n"]
    if missing:
        raise RuntimeError(
            f"{missing} reaction(s) have no account, so the reactions table cannot be migrated"
        )
    conn.execute("ALTER TABLE reactions RENAME TO reactions__pre_polymorphic")
    try:
        conn.execute(
            """
            CREATE TABLE reactions (
                "id" blob NOT NULL PRIMARY KEY,
                "account_id" blob NOT NULL,
                "content" varchar(16) NOT NULL,
                "created_at" datetime(6) NOT NULL,
                "reactable_id" blob NOT NULL,
                "reactable_type" varchar(255) NOT NULL,
                "reacter_id" blob NOT NULL,
                "updated_at" datetime(6) NOT NULL
            )
            """
        )
        conn.execute(
            f"""
            INSERT INTO reactions (
                id, account_id, content, created_at, reactable_id, reactable_type, reacter_id, updated_at
            )
            SELECT old.id, {account_sql}, old.content, old.created_at,
                   {reactable_id_sql}, {reactable_type_sql}, old.reacter_id, old.updated_at
            FROM reactions__pre_polymorphic AS old
            LEFT JOIN comments ON comments.id = old.comment_id
            """
        )
        conn.execute("DROP TABLE reactions__pre_polymorphic")
        conn.execute('CREATE INDEX "index_reactions_on_account_id" ON reactions (account_id)')
        conn.execute(
            'CREATE INDEX "index_reactions_on_reactable_type_and_reactable_id" '
            "ON reactions (reactable_type, reactable_id)"
        )
        conn.execute('CREATE INDEX "index_reactions_on_reacter_id" ON reactions (reacter_id)')
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
            (REACTIONS_POLYMORPHIC_VERSION,),
        )
        conn.commit()
    except Exception:
        names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "reactions__pre_polymorphic" in names:
            if "reactions" in names:
                conn.execute("DROP TABLE reactions")
            conn.execute("ALTER TABLE reactions__pre_polymorphic RENAME TO reactions")
            conn.commit()
        raise


def ensure(conn) -> None:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='accounts'"
    ).fetchone()
    if not row:
        conn.execute("PRAGMA foreign_keys=OFF")
        for statement in statements():
            conn.execute(statement)
        conn.execute(
            'INSERT INTO schema_migrations (version) VALUES (?)', (SCHEMA_VERSION,)
        )
        now = "1970-01-01 00:00:00.000000"
        conn.execute(
            'INSERT INTO ar_internal_metadata (key, value, created_at, updated_at) VALUES (?, ?, ?, ?)',
            ("environment", "development", now, now),
        )
        conn.commit()
    _migrate_reactions(conn)
