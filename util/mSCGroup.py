# ================================================================
# A simple class for ingestion of anndata to a TileDB group.
#
# * The write path (anndata/10X -> TileDB) is exercised here
#
# * A read path (TileDB -> anndata/10X) is a WIP.
#
# * The class structure in this source file is likely to change but the
#   TileDB Groups this code creates should remain relatively stable, modulo
#   updates to the Matrix API itself and/or any errors encountered during testing.
#
# * The filename is mSCGroup.py not SCGroup.py since if I have `SCGroup.py` with `class SCGroup`
#   then I can’t do `from SCGroup import SCGroup`.
#
# * See also desc-ann.py in this directory for helpful information to
#   reveal the diversity/variety of HD5 files we process.
# ================================================================

import os

import anndata as ad
import numpy   as np
import pandas  as pd
import pyarrow as pa
import scanpy
import scipy
import tiledb


class SCGroup():
    """ Single-cell group

    Class for representing a group of TileDB arrays that consitute an `sc_group`,
    which includes:
    - `X` ([`AssayMatrixGroup`]): a group of one or more labeled 2D sparse arrays
      that share the same dimensions.
    - `obs` ([`AnnotationDataframe`]): 1D labeled array with column labels for
      `X`
    - `var` ([`AnnotationDataframe`]): 1D labeled array with row labels for `X`
    """

    uri: str
    verbose: bool

    # ----------------------------------------------------------------
    def __init__(self, uri, verbose=True):
        """
        @description Create a new SCGroup object. The existing array group is
          opened at the specified array `uri` if one is present, otherwise a new
          array group is created.
        @param uri URI of the TileDB group
        @param verbose Print status messages
        """

        self.uri = uri
        self.verbose = verbose

        # If URI is "/something/test1" then:
        # * obs_uri  is "/something/test1/obs"
        # * var_uri  is "/something/test1/var"
        # * data_uri is "/something/test1/X"

        # If URI is "tiledb://namespace/s3://bucketname/something/test1" then:
        # * obs_uri  is "tiledb://namespace/s3://bucketname/something/test1/obs"
        # * var_uri  is "tiledb://namespace/s3://bucketname/something/test1/var"
        # * data_uri is "tiledb://namespace/s3://bucketname/something/test1/X"

    # ----------------------------------------------------------------
    def from_h5ad(self, input_path):
        if self.verbose:
            print("START  SCGroup.from_h5ad %s -> %s" % (input_path, self.uri))

        anndata = self.read_h5ad(input_path)

        anndata = self.decategoricalize(anndata)

        self.write_tiledb_group(anndata)

        if self.verbose:
            print("FINISH SCGroup.from_h5ad %s -> %s" % (input_path, self.uri))

    # ----------------------------------------------------------------
    def from_10x(self, input_path):
        if self.verbose:
            print("START  SCGroup.from_10x %s -> %s" % (input_path, self.uri))

        anndata = self.read_10x(input_path)

        anndata = self.decategoricalize(anndata)

        self.write_tiledb_group(anndata)

        if self.verbose:
            print("FINISH SCGroup.from_10x %s -> %s" % (input_path, self.uri))

    # ----------------------------------------------------------------
    def read_h5ad(self, input_path):
        if self.verbose:
            print("  START  READING %s" % (input_path))
        anndata = ad.read_h5ad(input_path)
        anndata.var_names_make_unique()
        if self.verbose:
            print("  FINISH READING %s" % (input_path))
        return anndata

    # ----------------------------------------------------------------
    def read_10x(self, input_path):
        if self.verbose:
            print("  START  READING %s" % (input_path))
        anndata = scanpy.read_10x_h5(input_path)
        anndata.var_names_make_unique()
        if self.verbose:
            print("  FINISH READING %s" % (input_path))
        return anndata

    # ----------------------------------------------------------------
    def decategoricalize(self, anndata):
        """
        Performs a typecast for the categorical datatype that pandas can handle.
        We cast this to Python 'object' which in this case means 'string'.
        The uns and raw datasets are deferred.
        """

        if self.verbose:
            print("  START  DECATEGORICALIZING")

        uncat = lambda x: x.astype("O") if isinstance(x.dtype, pd.CategoricalDtype) else x

        obs  = pd.DataFrame.from_dict({k: uncat(v) for k,v in anndata.obs.items()})
        var  = pd.DataFrame.from_dict({k: uncat(v) for k,v in anndata.var.items()})

        for key in anndata.obsm.keys():
            anndata.obsm[key] = uncat(anndata.obsm[key])
        for key in anndata.varm.keys():
            anndata.varm[key] = uncat(anndata.varm[key])
        for key in anndata.obsp.keys():
            anndata.obsp[key] = uncat(anndata.obsp[key])
        for key in anndata.varp.keys():
            anndata.varp[key] = uncat(anndata.varp[key])

        anndata = ad.AnnData(
    	    X=anndata.X,
    	    obs=obs,
    	    var=var,
    	    obsm=anndata.obsm,
    	    obsp=anndata.obsp,
    	    varm=anndata.varm,
    	    varp=anndata.varp,
        )

        if self.verbose:
            print("  FINISH DECATEGORICALIZING")
        return anndata

    # ----------------------------------------------------------------
    def write_tiledb_group(self, anndata):
        if self.verbose:
            print("  START  WRITING %s" % (self.uri))

        # ----------------------------------------------------------------
        # Must be done first, to create the parent directory
        tiledb.group_create(self.uri)
        base_group = tiledb.Group(self.uri, "w")

        # ----------------------------------------------------------------
        X_uri = self.write_X(anndata)
        base_group.add(uri=X_uri, relative=False, name="X")

        # ----------------------------------------------------------------
        obs_uri = self.write_obs_or_var(anndata.obs, "obs")
        base_group.add(uri=obs_uri, relative=False, name="obs")

        var_uri = self.write_obs_or_var(anndata.var, "var")
        base_group.add(uri=var_uri, relative=False, name="var")

        # ----------------------------------------------------------------
        if len(anndata.obsm.keys()) > 0:
            obsm_uri = self.write_annotation_matrices(anndata.obsm, "obsm")
            base_group.add(uri=obsm_uri, relative=False, name="obsm")

        if len(anndata.varm.keys()) > 0:
            varm_uri = self.write_annotation_matrices(anndata.varm, "varm")
            base_group.add(uri=varm_uri, relative=False, name="varm")

        if len(anndata.obsp.keys()) > 0:
            obsp_uri = self.write_annotation_matrices(anndata.obsp, "obsp")
            base_group.add(uri=obsp_uri, relative=False, name="obsp")

        if len(anndata.varp.keys()) > 0:
            varp_uri = self.write_annotation_matrices(anndata.varp, "varp")
            base_group.add(uri=varp_uri, relative=False, name="varp")

        # ----------------------------------------------------------------
        if self.verbose:
            print("  FINISH WRITING %s" % (self.uri))

        base_group.close()

    # ----------------------------------------------------------------
    def write_X(self, anndata):
        X_uri = os.path.join(self.uri, "X")
        tiledb.group_create(X_uri)
        X_group = tiledb.Group(X_uri, "w")

        X_data_uri = os.path.join(X_uri, "data")
        if self.verbose:
            print("    START  WRITING %s" % (X_data_uri))

        # Here we do not use tiledb.from_numpy, so that we can have more control over the schema.

        obs_dim, var_dim = np.meshgrid(anndata.obs.index, anndata.var.index)

        dom = tiledb.Domain(
            tiledb.Dim(name="obs_id", domain=(None, None), dtype="ascii"),
            tiledb.Dim(name="var_id", domain=(None, None), dtype="ascii"),
        )
        att = tiledb.Attr("data")
        sch = tiledb.ArraySchema(domain=dom, attrs=(att,), sparse=True)
        tiledb.Array.create(X_data_uri, sch)

        with tiledb.open(X_data_uri, "w") as A:
            A[np.ravel(obs_dim), np.ravel(var_dim)] = anndata.X.flatten()

        X_group.add(uri=X_data_uri, relative=False, name="data")
        if self.verbose:
            print("    FINISH WRITING %s" % (X_data_uri))

        X_group.close()

        return X_uri

    # ----------------------------------------------------------------
    def write_obs_or_var(self, obs_or_var_data, obs_or_var_name):
        """
        First argument is anndata.obs or anndata.var; second is "obs" or "var".  In the reference
        pbmc3k_processed dataset, these are of type pandas.core.frame.DataFrame. In further
        testing we may need to switch on the datatype.
        """
    
        offsets_filters = tiledb.FilterList(
            [tiledb.PositiveDeltaFilter(), tiledb.ZstdFilter(level=-1)]
        )
        coords_filters = tiledb.FilterList([tiledb.ZstdFilter(level=-1)])
        dim_filters = tiledb.FilterList([tiledb.ZstdFilter(level=-1)])
        attr_filters = tiledb.FilterList([tiledb.ZstdFilter(level=-1)])

        obs_or_var_uri = os.path.join(self.uri, obs_or_var_name)
        if self.verbose:
            print("    START  WRITING %s" % (obs_or_var_uri))

        tiledb.from_pandas(
            uri=obs_or_var_uri,
            dataframe=obs_or_var_data,
            name=obs_or_var_name,
            sparse=True,
            allows_duplicates=False,
            coords_filters=coords_filters,
            offsets_filters=offsets_filters,
            attr_filters=attr_filters,
            dim_filters=dim_filters
        )

        if self.verbose:
            print("    FINISH WRITING %s" % (obs_or_var_uri))

        return obs_or_var_uri

    # ----------------------------------------------------------------
    def write_annotation_matrices(self, annotation_matrices, name):
        """
        Input: anndata.obsm, anndata.varm, anndata.obsp, or anndata.varp, along with the name
        "obsm", "varm", "obsp", or "varp", respectively. Each component array from the HD5 file
        should be a numpy.ndarray or scipy.sparse.csr.csr_matrix.  Writes the TileDB obsm, varm,
        obsp, or varp group under the base scgroup URI, and then writes all the component arrays
        under that.
        """
        subgroup_uri = os.path.join(self.uri, name)
        tiledb.group_create(subgroup_uri)
        subgroup = tiledb.Group(subgroup_uri, "w")
        for name in annotation_matrices.keys():
            component_array_uri = os.path.join(subgroup_uri, name)
            if self.verbose:
                print("    START  WRITING %s" % (component_array_uri))

            # Check for conversion from pandas if necessary.  For the pbmc3k_processed reference
            # dataset, obsm and varm matrices are numpy.ndarray while obsp matrices are
            # scipy.sparse.csr.csr_matrix. For ongoing work we will likely need more checks
            # here. See also desc-ann.py in this directory which helps reveal the datatypes
            # contained within a given HD5 file.
            input_as_np_array = annotation_matrices[name]
            if isinstance(input_as_np_array, scipy.sparse.csr.csr_matrix):
                input_as_np_array = input_as_np_array.toarray()

            tiledb.from_numpy(
                uri=component_array_uri,
                array=input_as_np_array
            )

            if self.verbose:
                print("    FINISH WRITING %s" % (component_array_uri))

            subgroup.add(uri=component_array_uri, relative=False, name=name)
        subgroup.close()

        return subgroup_uri
