'''
Abstract class for forcing the implementation of the method 'metrics_setup' in
the derived classes.
'''

from abc import ABC


class Metrics(ABC):
    def metrics_setup(self) -> None:
        '''
        Set up the metrics for the cache
        '''
        pass
