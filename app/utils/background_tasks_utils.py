from fastapi import BackgroundTasks, Request


def add_background_task(
    background_tasks: BackgroundTasks, task_func, request: Request, *args, **kwargs
):
    background_tasks.add_task(task_func, request, *args, **kwargs)
