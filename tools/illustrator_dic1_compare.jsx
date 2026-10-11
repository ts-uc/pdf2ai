#target illustrator
(function () {
    var root = new File($.fileName).parent.parent;
    function json(value) {
        if (value === null) return 'null';
        if (typeof value == 'string') return '"' + value.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\r/g, '\\r').replace(/\n/g, '\\n') + '"';
        if (typeof value != 'object') return String(value);
        var parts = [], key;
        if (value instanceof Array) {
            for (var i = 0; i < value.length; i++) parts.push(json(value[i]));
            return '[' + parts.join(',') + ']';
        }
        for (key in value) if (value.hasOwnProperty(key)) parts.push(json(key) + ':' + json(value[key]));
        return '{' + parts.join(',') + '}';
    }
    function array(value) {
        var result = [];
        for (var i = 0; i < value.length; i++) result.push(value[i]);
        return result;
    }
    function color(value) {
        if (!value) return null;
        var result = {type:value.typename};
        if (value.typename == 'SpotColor') {
            result.name = value.spot.name; result.tint = value.tint;
            result.base = color(value.spot.color);
        } else if (value.typename == 'CMYKColor') {
            result.values = [value.cyan,value.magenta,value.yellow,value.black];
        }
        return result;
    }
    var names = ['dic1_exported.ai','dic1_fromai.ai'], results = [];
    var request = new File(root + '/output/dic1-comparison-request.json');
    if (request.exists) {
        request.encoding = 'UTF-8'; request.open('r');
        var config = eval('(' + request.read() + ')'); request.close();
        names = config.files;
    }
    var previous = app.userInteractionLevel;
    try {
        app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;
        for (var f = 0; f < names.length; f++) {
            var doc = app.open(new File(names[f].charAt(0) == '/' ? names[f] : root.parent + '/' + names[f]));
            try {
                var result = {file:names[f],version:app.version,colorSpace:String(doc.documentColorSpace),
                    rulerUnits:String(doc.rulerUnits),artboards:[],layers:[],paths:[],
                    images:doc.rasterItems.length,text:doc.textFrames.length,
                    placedItems:doc.placedItems.length,groups:doc.groupItems.length,
                    compoundPaths:doc.compoundPathItems.length};
                for (var a = 0; a < doc.artboards.length; a++) result.artboards.push({
                    name:doc.artboards[a].name,rect:array(doc.artboards[a].artboardRect)});
                for (var l = 0; l < doc.layers.length; l++) result.layers.push({
                    name:doc.layers[l].name,visible:doc.layers[l].visible,
                    locked:doc.layers[l].locked,printable:doc.layers[l].printable});
                for (var p = 0; p < doc.pathItems.length; p++) {
                    var path = doc.pathItems[p], points = [];
                    for (var n = 0; n < path.pathPoints.length; n++) {
                        var point = path.pathPoints[n];
                        points.push({anchor:array(point.anchor),left:array(point.leftDirection),right:array(point.rightDirection)});
                    }
                    result.paths.push({closed:path.closed,filled:path.filled,stroked:path.stroked,
                        clipping:path.clipping,evenodd:path.evenodd,opacity:path.opacity,
                        fillOverprint:path.fillOverprint,strokeOverprint:path.strokeOverprint,
                        strokeWidth:path.strokeWidth,fill:color(path.fillColor),stroke:color(path.strokeColor),
                        bounds:array(path.geometricBounds),points:points});
                }
                results.push(result);
            } finally {doc.close(SaveOptions.DONOTSAVECHANGES);}
        }
    } finally {app.userInteractionLevel = previous;}
    var output = new File(root + '/output/dic1-comparison.json'); output.encoding = 'UTF-8';
    if (!output.open('w')) throw new Error('Cannot write comparison');
    output.write(json(results)); output.close();
    return json(results);
}());
