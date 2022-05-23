import tiledb
from .soma_options import SOMAOptions
from .tiledb_object import TileDBObject

from typing import Optional, Union, List, Dict
import os


class TileDBGroup(TileDBObject):
    """
    Wraps groups from TileDB-Py by retaining a URI, verbose flag, etc.
    """

    tiledb_group: Union[tiledb.Group, None]

    def __init__(
        self,
        uri: str,
        name: str,
        # Non-top-level objects can have a parent to propgate context, depth, etc.
        # What we really want to say is:
        # parent: Optional[TileDBGroup] = None,
        parent=None,
        # Top-level objects should specify these:
        soma_options: Optional[SOMAOptions] = None,
        verbose: Optional[bool] = True,
        ctx: Optional[tiledb.Ctx] = None,
    ):
        """
        See the TileDBObject constructor.
        """
        super().__init__(uri=uri, name=name, parent=parent)

        self.tiledb_group = None

    def object_type(self):
        """
        This should be implemented by child classes and should return what tiledb.object_type(uri)
        returns for objects of a given type -- nominally 'group' or 'array'.
        """
        return "group"

    def exists(self) -> bool:
        """
        Tells whether or not there is storage for the group. This might be in case a SOMA
        object has not yet been populated, e.g. before calling `from_anndata` -- or, if the
        SOMA has been populated but doesn't have this member (e.g. not all SOMAs have a `varp`).
        """
        return tiledb.object_type(self.uri) == "group"

    def create(self):
        """
        Creates the TileDB group data structure on disk/S3/cloud.
        """
        if self.tiledb_group != None:
            raise Exception("Attempt to create an already-open group")
        if self.verbose:
            print(f"{self.indent}Creating TileDB group {self.uri}")
        tiledb.group_create(uri=self.uri, ctx=self.ctx)

    def open(self, mode: str):
        """
        Mode must be "w" for write or "r" for read.
        """
        assert mode in ["w", "r"]
        if self.tiledb_group != None:
            raise Exception("Attempt to open an already-open group")
        if not self.exists():
            self.create()
        self.tiledb_group = tiledb.Group(self.uri, mode=mode, ctx=self.ctx)

    def close(self):
        """
        Should be done after open-with-write and add, or, open-with-read and read.
        """
        if self.tiledb_group == None:
            raise Exception("Attempt to close a non-open group")
        self.tiledb_group.close()
        self.tiledb_group = None

    def add_object(self, obj: TileDBObject):
        if self.tiledb_group == None:
            raise Exception("Attempt to write to a non-open group")
        self.tiledb_group.add(uri=obj.uri, relative=False, name=obj.name)

    def add_uri(self, uri: str, name: str):
        if self.tiledb_group == None:
            raise Exception("Attempt to write to a non-open group")
        self.tiledb_group.add(uri=uri, relative=False, name=name)

    def get_member_names(self):
        """
        Returns the names of the group elements. For a SOMACollection, these will SOMA names;
        for a SOMA, these will be matrix/group names; etc.
        """
        return [os.path.basename(e) for e in self.get_member_uris()]

    def get_member_uris(self) -> List[str]:
        """
        Returns the URIs of the group elements. For a SOMACollection, these will SOMA URIs;
        for a SOMA, these will be matrix/group URIs; etc.
        """
        self.open("r")
        retval = [e.uri for e in self.tiledb_group]
        self.close()
        return retval

    def get_member_names_to_uris(self) -> Dict[str, str]:
        """
        Like `get_member_names()` and `get_member_uris`, but returns a dict mapping from
        member name to member URI.
        """
        retval = {}
        self.open("r")
        for e in self.tiledb_group:
            name = os.path.basename(e.uri)
            retval[name] = e.uri
        self.close()
        return retval
