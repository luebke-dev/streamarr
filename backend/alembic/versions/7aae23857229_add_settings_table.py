"""Add settings table

Revision ID: 7aae23857229
Revises: 8ddc19538838
Create Date: 2026-01-17 22:41:29.960171

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7aae23857229'
down_revision: Union[str, Sequence[str], None] = '8ddc19538838'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create settings table
    op.create_table('settings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('key', sa.String(), nullable=False),
    sa.Column('value', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_settings_key'), 'settings', ['key'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop settings table
    op.drop_index(op.f('ix_settings_key'), table_name='settings')
    op.drop_table('settings')

    op.drop_index(op.f('ix_banners_banner_type'), table_name='banners')
    op.drop_index(op.f('ix_banners_created_at'), table_name='banners')
    op.drop_index(op.f('ix_banners_created_by_guid'), table_name='banners')
    op.drop_index(op.f('ix_banners_dismissible'), table_name='banners')
    op.drop_index(op.f('ix_banners_end_date'), table_name='banners')
    op.drop_index(op.f('ix_banners_is_active'), table_name='banners')
    op.drop_index(op.f('ix_banners_start_date'), table_name='banners')
    op.drop_index(op.f('ix_banners_title'), table_name='banners')
    op.drop_table('banners')
    op.drop_index(op.f('ix_media_release_link_link_type'), table_name='media_release_link')
    op.drop_index(op.f('ix_media_release_link_media_release_guid'), table_name='media_release_link')
    op.drop_table('media_release_link')
    op.drop_index(op.f('ix_download_downloader_id'), table_name='download')
    op.drop_index(op.f('ix_download_external_id'), table_name='download')
    op.drop_index(op.f('ix_download_media_release_link_guid'), table_name='download')
    op.drop_index(op.f('ix_download_status'), table_name='download')
    op.drop_index(op.f('ix_download_title'), table_name='download')
    op.drop_index(op.f('ix_download_type'), table_name='download')
    op.drop_table('download')
    op.drop_index(op.f('ix_watch_party_member_is_connected'), table_name='watch_party_member')
    op.drop_index(op.f('ix_watch_party_member_party_id'), table_name='watch_party_member')
    op.drop_index(op.f('ix_watch_party_member_user_id'), table_name='watch_party_member')
    op.drop_table('watch_party_member')
    op.drop_index(op.f('ix_show_series_type_series_type'), table_name='show_series_type')
    op.drop_table('show_series_type')
    op.drop_index(op.f('ix_media_item_availability_status'), table_name='media_item')
    op.drop_index(op.f('ix_media_item_library_guid'), table_name='media_item')
    op.drop_index(op.f('ix_media_item_media_type'), table_name='media_item')
    op.drop_index(op.f('ix_media_item_original_title'), table_name='media_item')
    op.drop_index(op.f('ix_media_item_parent_guid'), table_name='media_item')
    op.drop_index(op.f('ix_media_item_title'), table_name='media_item')
    op.drop_table('media_item')
    op.drop_index(op.f('ix_user_session_session_token'), table_name='user_session')
    op.drop_table('user_session')
    op.drop_index(op.f('ix_subscription_package_name'), table_name='subscription_package')
    op.drop_table('subscription_package')
    op.drop_index(op.f('ix_indexer_api_key'), table_name='indexer')
    op.drop_index(op.f('ix_indexer_host'), table_name='indexer')
    op.drop_index(op.f('ix_indexer_label'), table_name='indexer')
    op.drop_index(op.f('ix_indexer_type'), table_name='indexer')
    op.drop_table('indexer')
    op.drop_index(op.f('ix_list_is_active'), table_name='list')
    op.drop_index(op.f('ix_list_list_type'), table_name='list')
    op.drop_index(op.f('ix_list_name'), table_name='list')
    op.drop_index(op.f('ix_list_owner_guid'), table_name='list')
    op.drop_index(op.f('ix_list_visibility'), table_name='list')
    op.drop_table('list')
    op.drop_index(op.f('ix_indexer_category_category_type'), table_name='indexer_category')
    op.drop_index(op.f('ix_indexer_category_label'), table_name='indexer_category')
    op.drop_table('indexer_category')
    op.drop_index(op.f('ix_media_release_indexer_guid'), table_name='media_release')
    op.drop_index(op.f('ix_media_release_media_item_guid'), table_name='media_release')
    op.drop_index(op.f('ix_media_release_quality'), table_name='media_release')
    op.drop_index(op.f('ix_media_release_score'), table_name='media_release')
    op.drop_index(op.f('ix_media_release_title'), table_name='media_release')
    op.drop_table('media_release')
    op.drop_index(op.f('ix_downloader_api_key'), table_name='downloader')
    op.drop_index(op.f('ix_downloader_host'), table_name='downloader')
    op.drop_index(op.f('ix_downloader_label'), table_name='downloader')
    op.drop_index(op.f('ix_downloader_type'), table_name='downloader')
    op.drop_table('downloader')
    op.drop_index(op.f('ix_device_device_id'), table_name='device')
    op.drop_index(op.f('ix_device_user_id'), table_name='device')
    op.drop_table('device')
    op.drop_index(op.f('ix_user_banner_dismissed_banner_guid'), table_name='user_banner_dismissed')
    op.drop_index(op.f('ix_user_banner_dismissed_dismissed_at'), table_name='user_banner_dismissed')
    op.drop_index(op.f('ix_user_banner_dismissed_user_guid'), table_name='user_banner_dismissed')
    op.drop_table('user_banner_dismissed')
    op.drop_index(op.f('ix_media_file_file_path'), table_name='media_file')
    op.drop_index(op.f('ix_media_file_media_item_guid'), table_name='media_file')
    op.drop_index(op.f('ix_media_file_quality'), table_name='media_file')
    op.drop_table('media_file')
    op.drop_table('payment_history')
    op.drop_index(op.f('ix_genre_name'), table_name='genre')
    op.drop_table('genre')
    op.drop_index(op.f('ix_scene_mapping_mapping_type'), table_name='scene_mapping')
    op.drop_index(op.f('ix_scene_mapping_media_item_guid'), table_name='scene_mapping')
    op.drop_index(op.f('ix_scene_mapping_scene_title'), table_name='scene_mapping')
    op.drop_index(op.f('ix_scene_mapping_source'), table_name='scene_mapping')
    op.drop_index(op.f('ix_scene_mapping_tvdb_id'), table_name='scene_mapping')
    op.drop_index(op.f('ix_scene_mapping_tvdb_season'), table_name='scene_mapping')
    op.drop_table('scene_mapping')
    op.drop_index(op.f('ix_installed_plugins_configured'), table_name='installed_plugins')
    op.drop_index(op.f('ix_installed_plugins_domain'), table_name='installed_plugins')
    op.drop_index(op.f('ix_installed_plugins_enabled'), table_name='installed_plugins')
    op.drop_table('installed_plugins')
    op.drop_index(op.f('ix_user_list_interaction_interaction_type'), table_name='user_list_interaction')
    op.drop_index(op.f('ix_user_list_interaction_list_guid'), table_name='user_list_interaction')
    op.drop_index(op.f('ix_user_list_interaction_user_guid'), table_name='user_list_interaction')
    op.drop_table('user_list_interaction')
    op.drop_index(op.f('ix_notification_status'), table_name='notification')
    op.drop_index(op.f('ix_notification_user_id'), table_name='notification')
    op.drop_table('notification')
    op.drop_index(op.f('ix_viewing_history_last_watched_at'), table_name='viewing_history')
    op.drop_index(op.f('ix_viewing_history_media_item_guid'), table_name='viewing_history')
    op.drop_index(op.f('ix_viewing_history_user_guid'), table_name='viewing_history')
    op.drop_table('viewing_history')
    op.drop_index(op.f('ix_list_item_added_by_guid'), table_name='list_item')
    op.drop_index(op.f('ix_list_item_item_guid'), table_name='list_item')
    op.drop_index(op.f('ix_list_item_item_type'), table_name='list_item')
    op.drop_index(op.f('ix_list_item_list_guid'), table_name='list_item')
    op.drop_table('list_item')
    op.drop_index(op.f('ix_media_external_id_external_id'), table_name='media_external_id')
    op.drop_index(op.f('ix_media_external_id_media_item_guid'), table_name='media_external_id')
    op.drop_index(op.f('ix_media_external_id_provider'), table_name='media_external_id')
    op.drop_table('media_external_id')
    op.drop_index(op.f('ix_libraries_name'), table_name='libraries')
    op.drop_index(op.f('ix_libraries_plugin_id'), table_name='libraries')
    op.drop_index(op.f('ix_libraries_type'), table_name='libraries')
    op.drop_table('libraries')
    op.drop_index(op.f('ix_invite_token'), table_name='invite')
    op.drop_table('invite')
    op.drop_index(op.f('ix_user_email'), table_name='user')
    op.drop_index(op.f('ix_user_first_name'), table_name='user')
    op.drop_index(op.f('ix_user_last_name'), table_name='user')
    op.drop_index(op.f('ix_user_oidc_provider'), table_name='user')
    op.drop_index(op.f('ix_user_oidc_sub'), table_name='user')
    op.drop_index(op.f('ix_user_preferred_username'), table_name='user')
    op.drop_table('user')
    op.drop_table('user_subscription')
    op.drop_table('media_genre')
    op.drop_index(op.f('ix_watch_party_is_active'), table_name='watch_party')
    op.drop_index(op.f('ix_watch_party_media_id'), table_name='watch_party')
    op.drop_index(op.f('ix_watch_party_media_type'), table_name='watch_party')
    op.drop_index(op.f('ix_watch_party_owner_id'), table_name='watch_party')
    op.drop_index(op.f('ix_watch_party_party_code'), table_name='watch_party')
    op.drop_table('watch_party')
    op.drop_index(op.f('ix_favorite_media_item_guid'), table_name='favorite')
    op.drop_index(op.f('ix_favorite_user_id'), table_name='favorite')
    op.drop_table('favorite')
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('favorite',
    sa.Column('guid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('user_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('media_item_guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['media_item_guid'], ['media_item.guid'], name=op.f('favorite_media_item_guid_fkey'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['user.guid'], name=op.f('favorite_user_id_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('guid', name=op.f('favorite_pkey')),
    sa.UniqueConstraint('user_id', 'media_item_guid', name=op.f('uq_favorite_user_media'), postgresql_include=[], postgresql_nulls_not_distinct=False)
    )
    op.create_index(op.f('ix_favorite_user_id'), 'favorite', ['user_id'], unique=False)
    op.create_index(op.f('ix_favorite_media_item_guid'), 'favorite', ['media_item_guid'], unique=False)
    op.create_table('watch_party',
    sa.Column('guid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('party_code', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('name', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('owner_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('media_id', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('media_type', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('media_title', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('current_time', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
    sa.Column('is_playing', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('playback_rate', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
    sa.Column('last_sync_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('is_active', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('ended_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('max_members', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('allow_control', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('expires_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['user.guid'], name='watch_party_owner_id_fkey'),
    sa.PrimaryKeyConstraint('guid', name='watch_party_pkey'),
    postgresql_ignore_search_path=False
    )
    op.create_index(op.f('ix_watch_party_party_code'), 'watch_party', ['party_code'], unique=True)
    op.create_index(op.f('ix_watch_party_owner_id'), 'watch_party', ['owner_id'], unique=False)
    op.create_index(op.f('ix_watch_party_media_type'), 'watch_party', ['media_type'], unique=False)
    op.create_index(op.f('ix_watch_party_media_id'), 'watch_party', ['media_id'], unique=False)
    op.create_index(op.f('ix_watch_party_is_active'), 'watch_party', ['is_active'], unique=False)
    op.create_table('media_genre',
    sa.Column('media_item_guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('genre_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['genre_id'], ['genre.id'], name=op.f('media_genre_genre_id_fkey'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['media_item_guid'], ['media_item.guid'], name=op.f('media_genre_media_item_guid_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('media_item_guid', 'genre_id', name=op.f('media_genre_pkey'))
    )
    op.create_table('user_subscription',
    sa.Column('guid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('user_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('package_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('status', postgresql.ENUM('ACTIVE', 'CANCELLED', 'EXPIRED', 'PENDING', 'FAILED', name='subscriptionstatus'), autoincrement=False, nullable=False),
    sa.Column('starts_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('expires_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('cancelled_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('stripe_subscription_id', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('stripe_customer_id', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('current_sessions', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['package_id'], ['subscription_package.guid'], name='user_subscription_package_id_fkey'),
    sa.ForeignKeyConstraint(['user_id'], ['user.guid'], name='user_subscription_user_id_fkey'),
    sa.PrimaryKeyConstraint('guid', name='user_subscription_pkey'),
    sa.UniqueConstraint('stripe_subscription_id', name='user_subscription_stripe_subscription_id_key', postgresql_include=[], postgresql_nulls_not_distinct=False),
    postgresql_ignore_search_path=False
    )
    op.create_table('user',
    sa.Column('guid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('email', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('first_name', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('last_name', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('is_active', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('is_superuser', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('oidc_sub', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('oidc_provider', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('preferred_username', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('picture', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('locale', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('hashed_password', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('groups', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('last_login', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('ui_language', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('audio_language', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('subtitle_language', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('quality_preferences', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True),
    sa.PrimaryKeyConstraint('guid', name='user_pkey'),
    postgresql_ignore_search_path=False
    )
    op.create_index(op.f('ix_user_preferred_username'), 'user', ['preferred_username'], unique=False)
    op.create_index(op.f('ix_user_oidc_sub'), 'user', ['oidc_sub'], unique=True)
    op.create_index(op.f('ix_user_oidc_provider'), 'user', ['oidc_provider'], unique=False)
    op.create_index(op.f('ix_user_last_name'), 'user', ['last_name'], unique=False)
    op.create_index(op.f('ix_user_first_name'), 'user', ['first_name'], unique=False)
    op.create_index(op.f('ix_user_email'), 'user', ['email'], unique=True)
    op.create_table('invite',
    sa.Column('guid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('created_by_user_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('token', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('expires_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('is_active', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('is_used', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('used_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('used_by_user_id', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('description', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('max_uses', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('current_uses', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['user.guid'], name=op.f('invite_created_by_user_id_fkey')),
    sa.ForeignKeyConstraint(['used_by_user_id'], ['user.guid'], name=op.f('invite_used_by_user_id_fkey')),
    sa.PrimaryKeyConstraint('guid', name=op.f('invite_pkey'))
    )
    op.create_index(op.f('ix_invite_token'), 'invite', ['token'], unique=True)
    op.create_table('libraries',
    sa.Column('guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('name', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('type', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('plugin_id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('path', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('enabled', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('settings', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('description', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.PrimaryKeyConstraint('guid', name='libraries_pkey'),
    postgresql_ignore_search_path=False
    )
    op.create_index(op.f('ix_libraries_type'), 'libraries', ['type'], unique=False)
    op.create_index(op.f('ix_libraries_plugin_id'), 'libraries', ['plugin_id'], unique=False)
    op.create_index(op.f('ix_libraries_name'), 'libraries', ['name'], unique=False)
    op.create_table('media_external_id',
    sa.Column('guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('media_item_guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('provider', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('external_id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['media_item_guid'], ['media_item.guid'], name=op.f('media_external_id_media_item_guid_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('guid', name=op.f('media_external_id_pkey'))
    )
    op.create_index(op.f('ix_media_external_id_provider'), 'media_external_id', ['provider'], unique=False)
    op.create_index(op.f('ix_media_external_id_media_item_guid'), 'media_external_id', ['media_item_guid'], unique=False)
    op.create_index(op.f('ix_media_external_id_external_id'), 'media_external_id', ['external_id'], unique=False)
    op.create_table('list_item',
    sa.Column('guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('list_guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('item_type', postgresql.ENUM('MOVIE', 'SHOW', 'GAME', 'EPISODE', name='listitemtype'), autoincrement=False, nullable=False),
    sa.Column('item_guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('order_index', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('added_by_guid', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('notes', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['added_by_guid'], ['user.guid'], name=op.f('list_item_added_by_guid_fkey'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['list_guid'], ['list.guid'], name=op.f('list_item_list_guid_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('guid', name=op.f('list_item_pkey'))
    )
    op.create_index(op.f('ix_list_item_list_guid'), 'list_item', ['list_guid'], unique=False)
    op.create_index(op.f('ix_list_item_item_type'), 'list_item', ['item_type'], unique=False)
    op.create_index(op.f('ix_list_item_item_guid'), 'list_item', ['item_guid'], unique=False)
    op.create_index(op.f('ix_list_item_added_by_guid'), 'list_item', ['added_by_guid'], unique=False)
    op.create_table('viewing_history',
    sa.Column('guid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('user_guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('media_item_guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('progress_seconds', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('duration_seconds', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('progress_percentage', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
    sa.Column('is_completed', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('last_watched_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('first_watched_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['media_item_guid'], ['media_item.guid'], name=op.f('viewing_history_media_item_guid_fkey'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_guid'], ['user.guid'], name=op.f('viewing_history_user_guid_fkey')),
    sa.PrimaryKeyConstraint('guid', name=op.f('viewing_history_pkey'))
    )
    op.create_index(op.f('ix_viewing_history_user_guid'), 'viewing_history', ['user_guid'], unique=False)
    op.create_index(op.f('ix_viewing_history_media_item_guid'), 'viewing_history', ['media_item_guid'], unique=False)
    op.create_index(op.f('ix_viewing_history_last_watched_at'), 'viewing_history', ['last_watched_at'], unique=False)
    op.create_table('notification',
    sa.Column('guid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('user_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('notification_type', postgresql.ENUM('INFO', 'WARNING', 'ERROR', 'SUCCESS', 'SYSTEM', name='notificationtype'), autoincrement=False, nullable=False),
    sa.Column('status', postgresql.ENUM('PENDING', 'SENT', 'FAILED', 'READ', name='notificationstatus'), autoincrement=False, nullable=False),
    sa.Column('subject', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('message', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('send_email', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('email_template', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('read_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('sent_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('error_message', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('send_attempts', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('extra_data', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.guid'], name=op.f('notification_user_id_fkey')),
    sa.PrimaryKeyConstraint('guid', name=op.f('notification_pkey'))
    )
    op.create_index(op.f('ix_notification_user_id'), 'notification', ['user_id'], unique=False)
    op.create_index(op.f('ix_notification_status'), 'notification', ['status'], unique=False)
    op.create_table('user_list_interaction',
    sa.Column('guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('user_guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('list_guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('interaction_type', postgresql.ENUM('LIKE', 'FOLLOW', 'BOOKMARK', name='userlistinteractiontype'), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['list_guid'], ['list.guid'], name=op.f('user_list_interaction_list_guid_fkey'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_guid'], ['user.guid'], name=op.f('user_list_interaction_user_guid_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('guid', name=op.f('user_list_interaction_pkey')),
    sa.UniqueConstraint('user_guid', 'list_guid', 'interaction_type', name=op.f('uq_user_list_interaction'), postgresql_include=[], postgresql_nulls_not_distinct=False)
    )
    op.create_index(op.f('ix_user_list_interaction_user_guid'), 'user_list_interaction', ['user_guid'], unique=False)
    op.create_index(op.f('ix_user_list_interaction_list_guid'), 'user_list_interaction', ['list_guid'], unique=False)
    op.create_index(op.f('ix_user_list_interaction_interaction_type'), 'user_list_interaction', ['interaction_type'], unique=False)
    op.create_table('installed_plugins',
    sa.Column('guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('domain', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('enabled', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('configured', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('builtin', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('config', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=False),
    sa.Column('version', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('installed_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.PrimaryKeyConstraint('guid', name=op.f('installed_plugins_pkey'))
    )
    op.create_index(op.f('ix_installed_plugins_enabled'), 'installed_plugins', ['enabled'], unique=False)
    op.create_index(op.f('ix_installed_plugins_domain'), 'installed_plugins', ['domain'], unique=True)
    op.create_index(op.f('ix_installed_plugins_configured'), 'installed_plugins', ['configured'], unique=False)
    op.create_table('scene_mapping',
    sa.Column('guid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), autoincrement=False, nullable=False),
    sa.Column('tvdb_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('media_item_guid', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('scene_title', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('season_number', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('mapping_type', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('source', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('priority', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['media_item_guid'], ['media_item.guid'], name=op.f('scene_mapping_media_item_guid_fkey'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('guid', name=op.f('scene_mapping_pkey'))
    )
    op.create_index(op.f('ix_scene_mapping_tvdb_season'), 'scene_mapping', ['tvdb_id', 'season_number'], unique=False)
    op.create_index(op.f('ix_scene_mapping_tvdb_id'), 'scene_mapping', ['tvdb_id'], unique=False)
    op.create_index(op.f('ix_scene_mapping_source'), 'scene_mapping', ['source'], unique=False)
    op.create_index(op.f('ix_scene_mapping_scene_title'), 'scene_mapping', ['scene_title'], unique=False)
    op.create_index(op.f('ix_scene_mapping_media_item_guid'), 'scene_mapping', ['media_item_guid'], unique=False)
    op.create_index(op.f('ix_scene_mapping_mapping_type'), 'scene_mapping', ['mapping_type'], unique=False)
    op.create_table('genre',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('name', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('genre_pkey'))
    )
    op.create_index(op.f('ix_genre_name'), 'genre', ['name'], unique=True)
    op.create_table('payment_history',
    sa.Column('guid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('user_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('subscription_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('amount_cents', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('currency', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('status', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('stripe_payment_intent_id', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('stripe_invoice_id', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('failure_reason', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('payment_metadata', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['subscription_id'], ['user_subscription.guid'], name=op.f('payment_history_subscription_id_fkey')),
    sa.ForeignKeyConstraint(['user_id'], ['user.guid'], name=op.f('payment_history_user_id_fkey')),
    sa.PrimaryKeyConstraint('guid', name=op.f('payment_history_pkey')),
    sa.UniqueConstraint('stripe_payment_intent_id', name=op.f('payment_history_stripe_payment_intent_id_key'), postgresql_include=[], postgresql_nulls_not_distinct=False)
    )
    op.create_table('media_file',
    sa.Column('guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('media_item_guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('file_path', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('file_name', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('file_size', sa.BIGINT(), autoincrement=False, nullable=True),
    sa.Column('duration', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('width', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('height', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('codec', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('bitrate', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('probe_data', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('quality', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('format', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('imported_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['media_item_guid'], ['media_item.guid'], name=op.f('media_file_media_item_guid_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('guid', name=op.f('media_file_pkey'))
    )
    op.create_index(op.f('ix_media_file_quality'), 'media_file', ['quality'], unique=False)
    op.create_index(op.f('ix_media_file_media_item_guid'), 'media_file', ['media_item_guid'], unique=False)
    op.create_index(op.f('ix_media_file_file_path'), 'media_file', ['file_path'], unique=False)
    op.create_table('user_banner_dismissed',
    sa.Column('guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('user_guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('banner_guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('dismissed_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['banner_guid'], ['banners.guid'], name=op.f('user_banner_dismissed_banner_guid_fkey'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_guid'], ['user.guid'], name=op.f('user_banner_dismissed_user_guid_fkey')),
    sa.PrimaryKeyConstraint('guid', name=op.f('user_banner_dismissed_pkey'))
    )
    op.create_index(op.f('ix_user_banner_dismissed_user_guid'), 'user_banner_dismissed', ['user_guid'], unique=False)
    op.create_index(op.f('ix_user_banner_dismissed_dismissed_at'), 'user_banner_dismissed', ['dismissed_at'], unique=False)
    op.create_index(op.f('ix_user_banner_dismissed_banner_guid'), 'user_banner_dismissed', ['banner_guid'], unique=False)
    op.create_table('device',
    sa.Column('guid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('user_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('device_id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('name', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('browser', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('platform', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('user_agent', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('language', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('device_info', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
    sa.Column('last_activity', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('last_ip_address', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('is_active', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('is_trusted', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('is_playing', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('current_media_type', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('current_media_guid', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('current_media_title', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('current_playback_position', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('current_playback_duration', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('playback_updated_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.guid'], name=op.f('device_user_id_fkey')),
    sa.PrimaryKeyConstraint('guid', name=op.f('device_pkey'))
    )
    op.create_index(op.f('ix_device_user_id'), 'device', ['user_id'], unique=False)
    op.create_index(op.f('ix_device_device_id'), 'device', ['device_id'], unique=False)
    op.create_table('downloader',
    sa.Column('guid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('label', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('host', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('api_key', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('type', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('ssl', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('verify_ssl', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.PrimaryKeyConstraint('guid', name='downloader_pkey'),
    postgresql_ignore_search_path=False
    )
    op.create_index(op.f('ix_downloader_type'), 'downloader', ['type'], unique=False)
    op.create_index(op.f('ix_downloader_label'), 'downloader', ['label'], unique=False)
    op.create_index(op.f('ix_downloader_host'), 'downloader', ['host'], unique=False)
    op.create_index(op.f('ix_downloader_api_key'), 'downloader', ['api_key'], unique=False)
    op.create_table('media_release',
    sa.Column('guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('media_item_guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('title', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('size', sa.BIGINT(), autoincrement=False, nullable=True),
    sa.Column('quality', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('release_metadata', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True),
    sa.Column('score', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('indexer_guid', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('publish_date', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['indexer_guid'], ['indexer.guid'], name='media_release_indexer_guid_fkey', ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['media_item_guid'], ['media_item.guid'], name='media_release_media_item_guid_fkey', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('guid', name='media_release_pkey'),
    postgresql_ignore_search_path=False
    )
    op.create_index(op.f('ix_media_release_title'), 'media_release', ['title'], unique=False)
    op.create_index(op.f('ix_media_release_score'), 'media_release', ['score'], unique=False)
    op.create_index(op.f('ix_media_release_quality'), 'media_release', ['quality'], unique=False)
    op.create_index(op.f('ix_media_release_media_item_guid'), 'media_release', ['media_item_guid'], unique=False)
    op.create_index(op.f('ix_media_release_indexer_guid'), 'media_release', ['indexer_guid'], unique=False)
    op.create_table('indexer_category',
    sa.Column('guid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), autoincrement=False, nullable=False),
    sa.Column('label', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('indexer_guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('category_type', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('language', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('resolution', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('platform', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['indexer_guid'], ['indexer.guid'], name=op.f('indexer_category_indexer_guid_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('guid', name=op.f('indexer_category_pkey'))
    )
    op.create_index(op.f('ix_indexer_category_label'), 'indexer_category', ['label'], unique=False)
    op.create_index(op.f('ix_indexer_category_category_type'), 'indexer_category', ['category_type'], unique=False)
    op.create_table('list',
    sa.Column('guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('name', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('description', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('list_type', postgresql.ENUM('SYSTEM', 'USER', name='listtype'), autoincrement=False, nullable=False),
    sa.Column('owner_guid', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('visibility', postgresql.ENUM('PRIVATE', 'PUBLIC', name='listvisibility'), autoincrement=False, nullable=False),
    sa.Column('is_active', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('auto_update', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('update_source', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('last_auto_update', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('tags', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('poster_path', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('item_count', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('like_count', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('follow_count', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['owner_guid'], ['user.guid'], name=op.f('list_owner_guid_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('guid', name=op.f('list_pkey'))
    )
    op.create_index(op.f('ix_list_visibility'), 'list', ['visibility'], unique=False)
    op.create_index(op.f('ix_list_owner_guid'), 'list', ['owner_guid'], unique=False)
    op.create_index(op.f('ix_list_name'), 'list', ['name'], unique=False)
    op.create_index(op.f('ix_list_list_type'), 'list', ['list_type'], unique=False)
    op.create_index(op.f('ix_list_is_active'), 'list', ['is_active'], unique=False)
    op.create_table('indexer',
    sa.Column('guid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('label', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('host', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('api_key', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('ssl', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('type', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('verify_ssl', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.PrimaryKeyConstraint('guid', name='indexer_pkey'),
    postgresql_ignore_search_path=False
    )
    op.create_index(op.f('ix_indexer_type'), 'indexer', ['type'], unique=False)
    op.create_index(op.f('ix_indexer_label'), 'indexer', ['label'], unique=False)
    op.create_index(op.f('ix_indexer_host'), 'indexer', ['host'], unique=False)
    op.create_index(op.f('ix_indexer_api_key'), 'indexer', ['api_key'], unique=False)
    op.create_table('subscription_package',
    sa.Column('guid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('name', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('description', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('price_cents', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('currency', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('is_active', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('allowed_libraries', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=False),
    sa.Column('max_quality_movies', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('max_quality_series', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('max_quality_music', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('max_concurrent_sessions', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('stripe_price_id', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('stripe_product_id', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.PrimaryKeyConstraint('guid', name='subscription_package_pkey'),
    sa.UniqueConstraint('stripe_price_id', name='subscription_package_stripe_price_id_key', postgresql_include=[], postgresql_nulls_not_distinct=False),
    postgresql_ignore_search_path=False
    )
    op.create_index(op.f('ix_subscription_package_name'), 'subscription_package', ['name'], unique=False)
    op.create_table('user_session',
    sa.Column('guid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('user_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('subscription_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('session_token', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('device_info', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('ip_address', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('last_activity', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('is_active', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('content_type', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('content_id', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['subscription_id'], ['user_subscription.guid'], name=op.f('user_session_subscription_id_fkey')),
    sa.ForeignKeyConstraint(['user_id'], ['user.guid'], name=op.f('user_session_user_id_fkey')),
    sa.PrimaryKeyConstraint('guid', name=op.f('user_session_pkey'))
    )
    op.create_index(op.f('ix_user_session_session_token'), 'user_session', ['session_token'], unique=True)
    op.create_table('media_item',
    sa.Column('guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('media_type', postgresql.ENUM('MOVIES', 'SHOWS', 'GAMES', 'MUSIC', 'BOOKS', 'AUDIOBOOKS', name='mediatype'), autoincrement=False, nullable=False),
    sa.Column('library_guid', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('title', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('original_title', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('description', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('tagline', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('release_date', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('poster_path', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('backdrop_path', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('availability_status', postgresql.ENUM('UNKNOWN', 'AVAILABLE', 'DOWNLOADABLE', 'UNAVAILABLE', name='availabilitystatus'), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('last_searched_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('last_metadata_updated_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('parent_guid', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('sequence_number', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('extra_data', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['library_guid'], ['libraries.guid'], name='media_item_library_guid_fkey', ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['parent_guid'], ['media_item.guid'], name='media_item_parent_guid_fkey', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('guid', name='media_item_pkey'),
    postgresql_ignore_search_path=False
    )
    op.create_index(op.f('ix_media_item_title'), 'media_item', ['title'], unique=False)
    op.create_index(op.f('ix_media_item_parent_guid'), 'media_item', ['parent_guid'], unique=False)
    op.create_index(op.f('ix_media_item_original_title'), 'media_item', ['original_title'], unique=False)
    op.create_index(op.f('ix_media_item_media_type'), 'media_item', ['media_type'], unique=False)
    op.create_index(op.f('ix_media_item_library_guid'), 'media_item', ['library_guid'], unique=False)
    op.create_index(op.f('ix_media_item_availability_status'), 'media_item', ['availability_status'], unique=False)
    op.create_table('show_series_type',
    sa.Column('media_item_guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('series_type', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('absolute_episode_offset', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('date_format', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['media_item_guid'], ['media_item.guid'], name=op.f('show_series_type_media_item_guid_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('media_item_guid', name=op.f('show_series_type_pkey'))
    )
    op.create_index(op.f('ix_show_series_type_series_type'), 'show_series_type', ['series_type'], unique=False)
    op.create_table('watch_party_member',
    sa.Column('guid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('party_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('user_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('is_host', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('is_connected', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('last_position', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('last_heartbeat', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('joined_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('left_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['party_id'], ['watch_party.guid'], name=op.f('watch_party_member_party_id_fkey')),
    sa.ForeignKeyConstraint(['user_id'], ['user.guid'], name=op.f('watch_party_member_user_id_fkey')),
    sa.PrimaryKeyConstraint('guid', name=op.f('watch_party_member_pkey'))
    )
    op.create_index(op.f('ix_watch_party_member_user_id'), 'watch_party_member', ['user_id'], unique=False)
    op.create_index(op.f('ix_watch_party_member_party_id'), 'watch_party_member', ['party_id'], unique=False)
    op.create_index(op.f('ix_watch_party_member_is_connected'), 'watch_party_member', ['is_connected'], unique=False)
    op.create_table('download',
    sa.Column('guid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('title', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('type', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('downloader_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('status', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('external_id', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('progress', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('media_release_link_guid', sa.UUID(), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['downloader_id'], ['downloader.guid'], name=op.f('download_downloader_id_fkey'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['media_release_link_guid'], ['media_release_link.guid'], name=op.f('download_media_release_link_guid_fkey'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('guid', name=op.f('download_pkey'))
    )
    op.create_index(op.f('ix_download_type'), 'download', ['type'], unique=False)
    op.create_index(op.f('ix_download_title'), 'download', ['title'], unique=False)
    op.create_index(op.f('ix_download_status'), 'download', ['status'], unique=False)
    op.create_index(op.f('ix_download_media_release_link_guid'), 'download', ['media_release_link_guid'], unique=False)
    op.create_index(op.f('ix_download_external_id'), 'download', ['external_id'], unique=False)
    op.create_index(op.f('ix_download_downloader_id'), 'download', ['downloader_id'], unique=False)
    op.create_table('media_release_link',
    sa.Column('guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('media_release_guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('link', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('link_type', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['media_release_guid'], ['media_release.guid'], name=op.f('media_release_link_media_release_guid_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('guid', name=op.f('media_release_link_pkey'))
    )
    op.create_index(op.f('ix_media_release_link_media_release_guid'), 'media_release_link', ['media_release_guid'], unique=False)
    op.create_index(op.f('ix_media_release_link_link_type'), 'media_release_link', ['link_type'], unique=False)
    op.create_table('banners',
    sa.Column('guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('title', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('message', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('banner_type', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('is_active', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('dismissible', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('start_date', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('end_date', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('created_by_guid', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['created_by_guid'], ['user.guid'], name=op.f('banners_created_by_guid_fkey')),
    sa.PrimaryKeyConstraint('guid', name=op.f('banners_pkey'))
    )
    op.create_index(op.f('ix_banners_title'), 'banners', ['title'], unique=False)
    op.create_index(op.f('ix_banners_start_date'), 'banners', ['start_date'], unique=False)
    op.create_index(op.f('ix_banners_is_active'), 'banners', ['is_active'], unique=False)
    op.create_index(op.f('ix_banners_end_date'), 'banners', ['end_date'], unique=False)
    op.create_index(op.f('ix_banners_dismissible'), 'banners', ['dismissible'], unique=False)
    op.create_index(op.f('ix_banners_created_by_guid'), 'banners', ['created_by_guid'], unique=False)
    op.create_index(op.f('ix_banners_created_at'), 'banners', ['created_at'], unique=False)
    op.create_index(op.f('ix_banners_banner_type'), 'banners', ['banner_type'], unique=False)
    op.drop_index(op.f('ix_settings_key'), table_name='settings')
    op.drop_table('settings')
    # ### end Alembic commands ###
