"""Tests for the ListService."""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.list import (
    ListItemType,
    ListType,
    ListVisibility,
    UserListInteractionType,
)
from pyrate.models.user import User
from pyrate.schemas.list import (
    ListCreate,
    ListItemCreate,
    ListUpdate,
    UserListInteractionCreate,
)
from pyrate.services.list import ListService


class TestListCRUD:
    """Test basic CRUD operations for lists."""

    @pytest.mark.asyncio
    async def test_create_user_list(self, db_session: AsyncSession, test_user: User):
        """Test creating a user list."""
        service = ListService(db_session)

        list_data = ListCreate(
            name="My Favorite Movies",
            description="Collection of my favorite movies",
            list_type=ListType.USER,
            visibility=ListVisibility.PRIVATE,
        )

        created_list = await service.create(list_data, owner_guid=str(test_user.guid))

        assert created_list.name == "My Favorite Movies"
        assert created_list.description == "Collection of my favorite movies"
        assert created_list.list_type == ListType.USER
        assert created_list.visibility == ListVisibility.PRIVATE
        assert str(created_list.owner_guid) == str(test_user.guid)
        assert created_list.is_active is True
        assert created_list.item_count == 0
        assert created_list.like_count == 0
        assert created_list.follow_count == 0

    @pytest.mark.asyncio
    async def test_create_system_list(self, db_session: AsyncSession):
        """Test creating a system list."""
        service = ListService(db_session)

        list_data = ListCreate(
            name="Trending Movies",
            description="Currently trending movies",
            list_type=ListType.SYSTEM,
            visibility=ListVisibility.PUBLIC,
            auto_update=True,
            update_source="tmdb_trending",
        )

        created_list = await service.create(list_data, owner_guid=None)

        assert created_list.name == "Trending Movies"
        assert created_list.list_type == ListType.SYSTEM
        assert created_list.visibility == ListVisibility.PUBLIC
        assert created_list.owner_guid is None
        assert created_list.auto_update is True
        assert created_list.update_source == "tmdb_trending"

    @pytest.mark.asyncio
    async def test_get_by_id(self, db_session: AsyncSession, test_user: User):
        """Test retrieving a list by ID."""
        service = ListService(db_session)

        list_data = ListCreate(
            name="Test List",
            list_type=ListType.USER,
            visibility=ListVisibility.PUBLIC,
        )
        created_list = await service.create(list_data, owner_guid=str(test_user.guid))

        retrieved_list = await service.get_by_id(str(created_list.guid))

        assert retrieved_list is not None
        assert retrieved_list.guid == created_list.guid
        assert retrieved_list.name == "Test List"
        assert retrieved_list.owner is not None
        assert str(retrieved_list.owner.guid) == str(test_user.guid)

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, db_session: AsyncSession):
        """Test retrieving a non-existent list."""
        service = ListService(db_session)

        retrieved_list = await service.get_by_id(str(uuid.uuid4()))

        assert retrieved_list is None

    @pytest.mark.asyncio
    async def test_update_list(self, db_session: AsyncSession, test_user: User):
        """Test updating a list."""
        service = ListService(db_session)

        list_data = ListCreate(
            name="Original Name",
            list_type=ListType.USER,
            visibility=ListVisibility.PRIVATE,
        )
        created_list = await service.create(list_data, owner_guid=str(test_user.guid))

        update_data = ListUpdate(
            name="Updated Name",
            description="New description",
            visibility=ListVisibility.PUBLIC,
        )

        updated_list = await service.update(created_list, update_data)

        assert updated_list.name == "Updated Name"
        assert updated_list.description == "New description"
        assert updated_list.visibility == ListVisibility.PUBLIC

    @pytest.mark.asyncio
    async def test_delete_list(self, db_session: AsyncSession, test_user: User):
        """Test deleting a list."""
        service = ListService(db_session)

        list_data = ListCreate(
            name="To Be Deleted",
            list_type=ListType.USER,
            visibility=ListVisibility.PRIVATE,
        )
        created_list = await service.create(list_data, owner_guid=str(test_user.guid))
        list_id = str(created_list.guid)

        await service.delete(created_list)

        deleted_list = await service.get_by_id(list_id)
        assert deleted_list is None


class TestListVisibilityAndFiltering:
    """Test list visibility and filtering logic."""

    @pytest.mark.asyncio
    async def test_get_all_public_lists(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test retrieving all public lists."""
        service = ListService(db_session)

        # Create public lists
        await service.create(
            ListCreate(
                name="Public List 1",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )
        await service.create(
            ListCreate(
                name="Public List 2",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user2.guid),
        )

        # Create private list (should not be visible without current_user_guid)
        await service.create(
            ListCreate(
                name="Private List",
                list_type=ListType.USER,
                visibility=ListVisibility.PRIVATE,
            ),
            owner_guid=str(test_user.guid),
        )

        lists, total = await service.get_all(
            current_user_guid=None, current_user_is_superuser=False
        )

        assert total == 2
        assert all(lst.visibility == ListVisibility.PUBLIC for lst in lists)

    @pytest.mark.asyncio
    async def test_private_list_visibility_owner(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test that private lists are visible to their owner."""
        service = ListService(db_session)

        await service.create(
            ListCreate(
                name="My Private List",
                list_type=ListType.USER,
                visibility=ListVisibility.PRIVATE,
            ),
            owner_guid=str(test_user.guid),
        )

        lists, total = await service.get_all(
            current_user_guid=str(test_user.guid), current_user_is_superuser=False
        )

        assert total == 1
        assert lists[0].visibility == ListVisibility.PRIVATE
        assert str(lists[0].owner_guid) == str(test_user.guid)

    @pytest.mark.asyncio
    async def test_private_list_not_visible_to_others(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test that private lists are not visible to other users."""
        service = ListService(db_session)

        await service.create(
            ListCreate(
                name="User1 Private List",
                list_type=ListType.USER,
                visibility=ListVisibility.PRIVATE,
            ),
            owner_guid=str(test_user.guid),
        )

        # Query as test_user2
        lists, total = await service.get_all(
            current_user_guid=str(test_user2.guid), current_user_is_superuser=False
        )

        assert total == 0

    @pytest.mark.asyncio
    async def test_filter_by_list_type(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test filtering lists by type."""
        service = ListService(db_session)

        await service.create(
            ListCreate(
                name="User List",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )
        await service.create(
            ListCreate(
                name="System List",
                list_type=ListType.SYSTEM,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=None,
        )

        # Filter for user lists only
        user_lists, user_total = await service.get_all(list_type=ListType.USER)
        assert user_total == 1
        assert user_lists[0].list_type == ListType.USER

        # Filter for system lists only
        system_lists, system_total = await service.get_all(list_type=ListType.SYSTEM)
        assert system_total == 1
        assert system_lists[0].list_type == ListType.SYSTEM

    @pytest.mark.asyncio
    async def test_filter_by_owner(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test filtering lists by owner."""
        service = ListService(db_session)

        await service.create(
            ListCreate(
                name="User1 List",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )
        await service.create(
            ListCreate(
                name="User2 List",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user2.guid),
        )

        lists, total = await service.get_all(
            owner_guid=str(test_user.guid),
            current_user_guid=str(test_user.guid),
        )

        assert total == 1
        assert str(lists[0].owner_guid) == str(test_user.guid)

    @pytest.mark.asyncio
    async def test_pagination(self, db_session: AsyncSession, test_user: User):
        """Test pagination of list results."""
        service = ListService(db_session)

        # Create 5 lists
        for i in range(5):
            await service.create(
                ListCreate(
                    name=f"List {i}",
                    list_type=ListType.USER,
                    visibility=ListVisibility.PUBLIC,
                ),
                owner_guid=str(test_user.guid),
            )

        # Get first page (2 items)
        lists_page1, total = await service.get_all(skip=0, limit=2)
        assert len(lists_page1) == 2
        assert total == 5

        # Get second page
        lists_page2, total = await service.get_all(skip=2, limit=2)
        assert len(lists_page2) == 2
        assert total == 5

        # Ensure pages contain different items
        page1_guids = {str(lst.guid) for lst in lists_page1}
        page2_guids = {str(lst.guid) for lst in lists_page2}
        assert page1_guids.isdisjoint(page2_guids)


class TestListItems:
    """Test list item operations."""

    @pytest.mark.asyncio
    async def test_add_item_to_list(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test adding an item to a list."""
        service = ListService(db_session)

        list_obj = await service.create(
            ListCreate(
                name="My Movies",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )

        item_guid = uuid.uuid4()
        item_data = ListItemCreate(
            item_type=ListItemType.MOVIE,
            item_guid=item_guid,
            notes="Great movie!",
        )

        item = await service.add_item(
            str(list_obj.guid), item_data, added_by_guid=str(test_user.guid)
        )

        assert item.item_type == ListItemType.MOVIE
        assert item.item_guid == item_guid
        assert item.notes == "Great movie!"
        assert str(item.list_guid) == str(list_obj.guid)
        assert str(item.added_by_guid) == str(test_user.guid)

        # Verify list item count was updated
        updated_list = await service.get_by_id(str(list_obj.guid))
        assert updated_list.item_count == 1

    @pytest.mark.asyncio
    async def test_add_duplicate_item_raises_error(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test that adding a duplicate item raises an error."""
        service = ListService(db_session)

        list_obj = await service.create(
            ListCreate(
                name="My Movies",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )

        item_guid = uuid.uuid4()
        item_data = ListItemCreate(
            item_type=ListItemType.MOVIE,
            item_guid=item_guid,
        )

        await service.add_item(str(list_obj.guid), item_data)

        # Try to add the same item again
        with pytest.raises(ValueError, match="Item already exists in list"):
            await service.add_item(str(list_obj.guid), item_data)

    @pytest.mark.asyncio
    async def test_add_item_rolls_back_duplicate_commit_race(
        self, db_session: AsyncSession, test_user: User, monkeypatch
    ):
        """Convert database duplicate races into the normal duplicate error."""
        service = ListService(db_session)

        list_obj = await service.create(
            ListCreate(
                name="My Race List",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )

        real_rollback = db_session.rollback
        rollback_mock = AsyncMock(side_effect=real_rollback)
        monkeypatch.setattr(
            db_session,
            "commit",
            AsyncMock(
                side_effect=IntegrityError(
                    statement="insert into list_items",
                    params={},
                    orig=Exception("duplicate key value violates unique constraint"),
                )
            ),
        )
        monkeypatch.setattr(db_session, "rollback", rollback_mock)

        item_data = ListItemCreate(
            item_type=ListItemType.MOVIE,
            item_guid=uuid.uuid4(),
        )

        with pytest.raises(ValueError, match="Item already exists in list"):
            await service.add_item(str(list_obj.guid), item_data)

        rollback_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_items_with_pagination(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test retrieving list items with pagination."""
        service = ListService(db_session)

        list_obj = await service.create(
            ListCreate(
                name="My Collection",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )

        # Add 5 items
        for _ in range(5):
            await service.add_item(
                str(list_obj.guid),
                ListItemCreate(
                    item_type=ListItemType.MOVIE,
                    item_guid=uuid.uuid4(),
                ),
            )

        # Get items with pagination
        items, total = await service.get_items(str(list_obj.guid), skip=0, limit=3)

        assert len(items) == 3
        assert total == 5

        # Get next page
        items_page2, total = await service.get_items(str(list_obj.guid), skip=3, limit=3)
        assert len(items_page2) == 2
        assert total == 5

    @pytest.mark.asyncio
    async def test_remove_item_from_list(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test removing an item from a list."""
        service = ListService(db_session)

        list_obj = await service.create(
            ListCreate(
                name="My Movies",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )

        item = await service.add_item(
            str(list_obj.guid),
            ListItemCreate(
                item_type=ListItemType.MOVIE,
                item_guid=uuid.uuid4(),
            ),
        )

        await service.remove_item(str(list_obj.guid), str(item.guid))

        # Verify item was removed
        items, total = await service.get_items(str(list_obj.guid))
        assert total == 0

        # Verify list item count was updated
        updated_list = await service.get_by_id(str(list_obj.guid))
        assert updated_list.item_count == 0

    @pytest.mark.asyncio
    async def test_remove_nonexistent_item_raises_error(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test that removing a non-existent item raises an error."""
        service = ListService(db_session)

        list_obj = await service.create(
            ListCreate(
                name="My Movies",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )

        with pytest.raises(ValueError, match="Item not found in list"):
            await service.remove_item(str(list_obj.guid), str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_item_count_updates_correctly(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test that item_count updates correctly when adding/removing items."""
        service = ListService(db_session)

        list_obj = await service.create(
            ListCreate(
                name="My Movies",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )

        # Add 3 items
        items = []
        for _ in range(3):
            item = await service.add_item(
                str(list_obj.guid),
                ListItemCreate(
                    item_type=ListItemType.MOVIE,
                    item_guid=uuid.uuid4(),
                ),
            )
            items.append(item)

        list_after_adds = await service.get_by_id(str(list_obj.guid))
        assert list_after_adds.item_count == 3

        # Remove 2 items
        await service.remove_item(str(list_obj.guid), str(items[0].guid))
        await service.remove_item(str(list_obj.guid), str(items[1].guid))

        list_after_removes = await service.get_by_id(str(list_obj.guid))
        assert list_after_removes.item_count == 1


class TestUserInteractions:
    """Test user interactions with lists (like, follow, bookmark)."""

    @pytest.mark.asyncio
    async def test_create_like_interaction(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test creating a like interaction."""
        service = ListService(db_session)

        list_obj = await service.create(
            ListCreate(
                name="Public List",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )

        interaction_data = UserListInteractionCreate(
            user_guid=test_user2.guid,
            list_guid=list_obj.guid,
            interaction_type=UserListInteractionType.LIKE,
        )

        interaction = await service.create_user_interaction(interaction_data)

        assert interaction.user_guid == test_user2.guid
        assert interaction.list_guid == list_obj.guid
        assert interaction.interaction_type == UserListInteractionType.LIKE

        # Verify like count was updated
        updated_list = await service.get_by_id(str(list_obj.guid))
        assert updated_list.like_count == 1

    @pytest.mark.asyncio
    async def test_create_follow_interaction(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test creating a follow interaction."""
        service = ListService(db_session)

        list_obj = await service.create(
            ListCreate(
                name="Public List",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )

        interaction_data = UserListInteractionCreate(
            user_guid=test_user2.guid,
            list_guid=list_obj.guid,
            interaction_type=UserListInteractionType.FOLLOW,
        )

        await service.create_user_interaction(interaction_data)

        # Verify follow count was updated
        updated_list = await service.get_by_id(str(list_obj.guid))
        assert updated_list.follow_count == 1

    @pytest.mark.asyncio
    async def test_create_bookmark_interaction(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test creating a bookmark interaction."""
        service = ListService(db_session)

        list_obj = await service.create(
            ListCreate(
                name="Public List",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )

        interaction_data = UserListInteractionCreate(
            user_guid=test_user2.guid,
            list_guid=list_obj.guid,
            interaction_type=UserListInteractionType.BOOKMARK,
        )

        interaction = await service.create_user_interaction(interaction_data)

        assert interaction.interaction_type == UserListInteractionType.BOOKMARK
        # Bookmark doesn't affect like_count or follow_count
        updated_list = await service.get_by_id(str(list_obj.guid))
        assert updated_list.like_count == 0
        assert updated_list.follow_count == 0

    @pytest.mark.asyncio
    async def test_duplicate_interaction_returns_existing(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test that creating a duplicate interaction returns the existing one."""
        service = ListService(db_session)

        list_obj = await service.create(
            ListCreate(
                name="Public List",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )

        interaction_data = UserListInteractionCreate(
            user_guid=test_user2.guid,
            list_guid=list_obj.guid,
            interaction_type=UserListInteractionType.LIKE,
        )

        interaction1 = await service.create_user_interaction(interaction_data)
        interaction2 = await service.create_user_interaction(interaction_data)

        assert interaction1.guid == interaction2.guid

        # Verify like count wasn't incremented twice
        updated_list = await service.get_by_id(str(list_obj.guid))
        assert updated_list.like_count == 1

    @pytest.mark.asyncio
    async def test_remove_like_interaction(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test removing a like interaction."""
        service = ListService(db_session)

        list_obj = await service.create(
            ListCreate(
                name="Public List",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )

        # Create interaction
        interaction_data = UserListInteractionCreate(
            user_guid=test_user2.guid,
            list_guid=list_obj.guid,
            interaction_type=UserListInteractionType.LIKE,
        )
        await service.create_user_interaction(interaction_data)

        # Remove interaction
        await service.remove_user_interaction(
            str(test_user2.guid),
            str(list_obj.guid),
            UserListInteractionType.LIKE,
        )

        # Verify like count was decremented
        updated_list = await service.get_by_id(str(list_obj.guid))
        assert updated_list.like_count == 0

        # Verify interaction was removed
        interaction = await service.get_user_interaction(
            str(test_user2.guid),
            str(list_obj.guid),
            UserListInteractionType.LIKE,
        )
        assert interaction is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent_interaction_does_nothing(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test that removing a non-existent interaction doesn't raise an error."""
        service = ListService(db_session)

        list_obj = await service.create(
            ListCreate(
                name="Public List",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )

        # This should not raise an error
        await service.remove_user_interaction(
            str(test_user2.guid),
            str(list_obj.guid),
            UserListInteractionType.LIKE,
        )

    @pytest.mark.asyncio
    async def test_interaction_counters_update_correctly(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test that interaction counters update correctly."""
        service = ListService(db_session)

        list_obj = await service.create(
            ListCreate(
                name="Public List",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )

        # Add like
        await service.create_user_interaction(
            UserListInteractionCreate(
                user_guid=test_user2.guid,
                list_guid=list_obj.guid,
                interaction_type=UserListInteractionType.LIKE,
            )
        )

        # Add follow
        await service.create_user_interaction(
            UserListInteractionCreate(
                user_guid=test_user2.guid,
                list_guid=list_obj.guid,
                interaction_type=UserListInteractionType.FOLLOW,
            )
        )

        list_after_adds = await service.get_by_id(str(list_obj.guid))
        assert list_after_adds.like_count == 1
        assert list_after_adds.follow_count == 1

        # Remove like
        await service.remove_user_interaction(
            str(test_user2.guid),
            str(list_obj.guid),
            UserListInteractionType.LIKE,
        )

        list_after_remove = await service.get_by_id(str(list_obj.guid))
        assert list_after_remove.like_count == 0
        assert list_after_remove.follow_count == 1


class TestUserSpecificQueries:
    """Test user-specific list queries."""

    @pytest.mark.asyncio
    async def test_get_user_lists(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test getting all lists owned by a user."""
        service = ListService(db_session)

        # Create lists for test_user
        await service.create(
            ListCreate(
                name="User1 Public List",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )
        await service.create(
            ListCreate(
                name="User1 Private List",
                list_type=ListType.USER,
                visibility=ListVisibility.PRIVATE,
            ),
            owner_guid=str(test_user.guid),
        )

        # Create list for test_user2
        await service.create(
            ListCreate(
                name="User2 List",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user2.guid),
        )

        # Get user1's lists (should include both public and private)
        lists, total = await service.get_user_lists(str(test_user.guid))

        assert total == 2
        assert all(str(lst.owner_guid) == str(test_user.guid) for lst in lists)

    @pytest.mark.asyncio
    async def test_get_user_liked_lists(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test getting lists liked by a user."""
        service = ListService(db_session)

        # Create lists
        list1 = await service.create(
            ListCreate(
                name="List 1",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )
        list2 = await service.create(
            ListCreate(
                name="List 2",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user.guid),
        )
        list3 = await service.create(
            ListCreate(
                name="List 3",
                list_type=ListType.USER,
                visibility=ListVisibility.PUBLIC,
            ),
            owner_guid=str(test_user2.guid),
        )

        # User2 likes list1 and list3
        await service.create_user_interaction(
            UserListInteractionCreate(
                user_guid=test_user2.guid,
                list_guid=list1.guid,
                interaction_type=UserListInteractionType.LIKE,
            )
        )
        await service.create_user_interaction(
            UserListInteractionCreate(
                user_guid=test_user2.guid,
                list_guid=list3.guid,
                interaction_type=UserListInteractionType.LIKE,
            )
        )

        # Get user2's liked lists
        liked_lists, total = await service.get_user_liked_lists(str(test_user2.guid))

        assert total == 2
        liked_guids = {str(lst.guid) for lst in liked_lists}
        assert str(list1.guid) in liked_guids
        assert str(list3.guid) in liked_guids
        assert str(list2.guid) not in liked_guids

    @pytest.mark.asyncio
    async def test_get_user_lists_pagination(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test pagination of user lists."""
        service = ListService(db_session)

        # Create 5 lists for test_user
        for i in range(5):
            await service.create(
                ListCreate(
                    name=f"List {i}",
                    list_type=ListType.USER,
                    visibility=ListVisibility.PUBLIC,
                ),
                owner_guid=str(test_user.guid),
            )

        # Get first page
        lists_page1, total = await service.get_user_lists(
            str(test_user.guid), skip=0, limit=2
        )
        assert len(lists_page1) == 2
        assert total == 5

        # Get second page
        lists_page2, total = await service.get_user_lists(
            str(test_user.guid), skip=2, limit=2
        )
        assert len(lists_page2) == 2
        assert total == 5
