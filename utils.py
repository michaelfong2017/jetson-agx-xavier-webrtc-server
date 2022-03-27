import logging
import time

def timeit(method):

    def timed(*args, **kw):
        ts = time.time()
        result = method(*args, **kw)
        te = time.time()
        logger = logging.getLogger()
        logger.info('{} {:.3f} sec'.format(method.__name__, te-ts))
        return result

    return timed