def classFactory(iface):
    from .RasterLoaderPlugin import RasterLoaderPlugin
    return RasterLoaderPlugin(iface)