#target illustrator
(function () {
    var folder = new Folder(new File($.fileName).parent.parent + '/output/multiboard-check');
    var files = folder.getFiles('*-combined.ai'), rows = ['Illustrator ' + app.version];
    var old = app.userInteractionLevel;
    function info(d) {
        var r = [d.artboards.length, d.pathItems.length, d.rasterItems.length];
        for (var j=0; j<d.artboards.length; j++) r.push(d.artboards[j].name, String(d.artboards[j].artboardRect));
        return r.join('\t');
    }
    try {
        app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;
        for (var i=0; i<files.length; i++) {
            var d = null;
            var filename = decodeURI(files[i].name);
            try {
                d = app.open(files[i]);
                var expected = 3;
                if (filename.indexOf('pages-') === 0) expected = 4;
                else if (filename.indexOf('fallback-') === 0) expected = 9;
                if (d.artboards.length != expected) throw new Error('Incorrect artboard count: ' + info(d) + '; expected=' + expected);
                for (var j=0; j<d.artboards.length; j++) {
                    if (d.artboards[j].name != 'Page ' + (j+1)) throw new Error('Incorrect artboard name: ' + d.artboards[j].name + '; ' + info(d));
                }
                var before = info(d);
                var options = new IllustratorSaveOptions(); options.pdfCompatible = true;
                var saved = new File(folder + '/' + files[i].name.replace('.ai', '-resaved.ai'));
                d.saveAs(saved, options); d.close(SaveOptions.DONOTSAVECHANGES); d = null;
                d = app.open(saved);
                var after = info(d);
                rows.push(files[i].name + '\t' + (before === after ? 'PASS' : 'DIFFERENCE') + '\t' + after);
                var pdf = new PDFSaveOptions(); pdf.preserveEditability = false;
                d.saveAs(new File(folder + '/' + files[i].name.replace('.ai', '-resaved.pdf')), pdf);
            } catch (e) { rows.push(files[i].name + '\tERROR\t' + String(e)); }
            finally { if (d) d.close(SaveOptions.DONOTSAVECHANGES); }
        }
    } finally { app.userInteractionLevel = old; }
    var f = new File(folder + '/illustrator-results.tsv'); f.encoding = 'UTF-8';
    f.open('w'); f.write(rows.join('\n')); f.close();
    return rows.join('\n');
}());
