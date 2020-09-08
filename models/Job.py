class Job:
    """
    Keeps info about job name which ideally is the last sub-dir of
    the job input file/CLI argument.
    """
    _name = ''

    @classmethod
    def update_name(cls, new_name):
        """Sets 'name' attribute to 'new_name' value."""
        cls._name = new_name

    @classmethod
    def get_name(cls):
        """Returns 'name' attribute."""
        return cls._name

    @classmethod
    def get_path_name(cls):
        """Returns 'name' attribute with '/' at the end."""
        name = cls.get_name()
        if name.endswith('/'):
            return name
        return name + '/'
