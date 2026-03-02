"""Tests for task_manager.py"""
import asyncio
from datetime import datetime, timedelta

from app.task_manager import Task, TaskManager, TaskStatus


async def test_add_task():
    """Test adding a task to the queue."""
    tm = TaskManager()
    task = tm.add_task(tool="claude", prompt="hello", delay_minutes=0)

    assert task.id
    assert task.tool == "claude"
    assert task.prompt == "hello"
    assert task.status == TaskStatus.QUEUED
    assert len(tm.queue) == 1


async def test_cancel_task():
    """Test cancelling a queued task."""
    tm = TaskManager()
    task = tm.add_task(tool="claude", prompt="test", delay_minutes=0)
    task_id = task.id

    ok = await tm.cancel_task(task_id)
    assert ok is True
    assert len(tm.queue) == 0
    assert len(tm.history) == 1
    assert tm.history[0].status == TaskStatus.CANCELLED


async def test_cancel_nonexistent():
    """Test cancelling a task that doesn't exist."""
    tm = TaskManager()
    ok = await tm.cancel_task("nonexistent")
    assert ok is False


async def test_get_state():
    """Test getting current state."""
    tm = TaskManager()
    task1 = tm.add_task(tool="claude", prompt="test1", delay_minutes=0)
    task2 = tm.add_task(tool="cursor", prompt="test2", delay_minutes=1)

    state = tm.get_state()
    assert len(state["queue"]) == 2
    assert state["queue"][0]["id"] == task1.id
    assert state["queue"][1]["id"] == task2.id


async def test_task_delay_scheduling():
    """Test that delayed tasks have scheduled_for set."""
    tm = TaskManager()
    task = tm.add_task(tool="claude", prompt="test", delay_minutes=5)

    assert task.scheduled_for is not None
    delta = (task.scheduled_for - datetime.now()).total_seconds()
    # Should be approximately 5 minutes (300 seconds)
    assert 299 < delta < 301


async def test_archive_respects_max_history():
    """Test that history doesn't exceed MAX_HISTORY."""
    tm = TaskManager()

    # Add 210 tasks
    for i in range(210):
        task = tm.add_task(tool="claude", prompt=f"test {i}", delay_minutes=0)
        tm._archive(task)

    # Should keep only last 200
    assert len(tm.history) == 200


def main():
    """Run all tests."""
    tests = [
        test_add_task,
        test_cancel_task,
        test_cancel_nonexistent,
        test_get_state,
        test_task_delay_scheduling,
        test_archive_respects_max_history,
    ]

    for test in tests:
        print(f"Running {test.__name__}...", end=" ")
        try:
            asyncio.run(test())
            print("✓")
        except AssertionError as e:
            print(f"✗ {e}")
            return 1
        except Exception as e:
            print(f"✗ Exception: {e}")
            return 1

    print(f"\n{len(tests)} tests passed ✓")
    return 0


if __name__ == "__main__":
    exit(main())
