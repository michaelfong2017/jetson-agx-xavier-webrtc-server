class TaskManager: 
    _instance = None 
    def __new__(cls, *args, **kwargs): 
        if cls._instance is None: 
            cls._instance = super().__new__(cls) 
        return cls._instance 
         
    def __init__(self, task="none"): 
        self.task = task

    def set_task(self, task):
        self.task = task
