#!/usr/bin/env python3


class LazyObject:
    def __init__(self, factory):
        self._factory = factory
        self._initialized = False
        self._object = None

    def _initialize(self):
        if not self._initialized:
            self._object = self._factory()
            self._initialized = True

    def __getattr__(self, name):
        self._initialize()
        return getattr(self._object, name)

    def __setattr__(self, name, value):
        if name in ('_initialized', '_object', '_factory'):
            return super().__setattr__(name, value)
        self._initialize()
        return setattr(self._object, name, value)

    @property
    def is_initialized(self):
        return self._initialized
