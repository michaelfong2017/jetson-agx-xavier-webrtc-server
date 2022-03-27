class TaskManager: 
    _instance = None 
    def __new__(cls, *args, **kwargs): 
        if cls._instance is None: 
            cls._instance = super().__new__(cls) 
        return cls._instance 
         
    def __init__(self, mirror=False, task="none"):
        self.mirror = mirror
        self.task = task

    def set_mirror(self, mirror):
        self.mirror = mirror

    def set_task(self, task):
        self.task = task
