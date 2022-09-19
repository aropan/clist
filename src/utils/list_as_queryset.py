class ListAsQueryset(list):

    def exists(self):
        return len(self) > 0

    def count(self):
        return len(self)

    def order_by(self, field):
        reverse = field.startswith('-')
        field = field.strip('-')
        self.sort(key=lambda el: (el.get(field) is not None, el.get(field)), reverse=reverse)
        return self
