class ListAsQueryset(list):

    def exists(self):
        return len(self) > 0

    def count(self):
        return len(self)
