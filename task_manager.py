from singleton import Singleton

class TaskManager(Singleton):          
    def __init__(self, mirror=False, task="none"):
        self.mirror = mirror
        self.task = task

    def set_mirror(self, mirror):
        self.mirror = mirror

    def set_task(self, task):
        self.task = task
