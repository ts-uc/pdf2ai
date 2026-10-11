#target illustrator
(function () {
    var base = new Folder(new File($.fileName).parent.parent + '/output/fidelity-check');
    var control = new File(base + '/run.json'); control.open('r');
    var config = eval('(' + control.read() + ')'); control.close();
    if (config.run != 'before' && config.run != 'after') throw new Error('Invalid run');
    var folder = new Folder(base + '/' + config.run);
    var out = new Folder(folder + '/illustrator'); if (!out.exists) out.create();
    var files = folder.getFiles('*.ai'), rows = ['Illustrator\t' + app.version];
    if (config.cases) {
        var selected=[];
        for(var f=0;f<files.length;f++)
            for(var c=0;c<config.cases.length;c++)
                if(decodeURI(files[f].name)==config.cases[c]) {selected.push(files[f]);break;}
        files=selected;
        if(files.length!=config.cases.length) throw new Error('Missing or duplicate selected cases');
    }
    var old = app.userInteractionLevel;
    try {
        app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;
        for (var i=0; i<files.length; i++) {
            var d = null, name = decodeURI(files[i].name);
            try {
                d = app.open(files[i]);
                var before = [d.artboards.length,d.pathItems.length,d.rasterItems.length,d.textFrames.length].join(',');
                var ai = new IllustratorSaveOptions(); ai.pdfCompatible = true;
                ai.compatibility = Compatibility.ILLUSTRATOR24;
                var saved = new File(out + '/' + name);
                d.saveAs(saved,ai); d.close(SaveOptions.DONOTSAVECHANGES); d=null;
                d = app.open(saved);
                var after = [d.artboards.length,d.pathItems.length,d.rasterItems.length,d.textFrames.length].join(',');
                var pdf = new PDFSaveOptions(); pdf.preserveEditability=false;
                pdf.compatibility = PDFCompatibility.ACROBAT7;
                pdf.colorConversionID = ColorConversion.None;
                pdf.colorDestinationID = ColorDestination.None;
                pdf.colorProfileID = ColorProfile.None;
                pdf.colorDownsampling = 0; pdf.grayscaleDownsampling = 0; pdf.monochromeDownsampling = 0;
                d.saveAs(new File(out + '/' + name.replace(/\.ai$/i,'.pdf')),pdf);
                rows.push(name + '\t' + (before == after ? 'PASS' : 'DIFFERENCE') + '\t' + after);
            } catch(e) { rows.push(name + '\tERROR\t' + String(e)); }
            finally { if(d) d.close(SaveOptions.DONOTSAVECHANGES); }
        }
    } finally { app.userInteractionLevel=old; }
    var report=new File(out+(config.cases ? '/results-selected.tsv' : '/results.tsv')); report.encoding='UTF-8';report.open('w');report.write(rows.join('\n'));report.close();
    return rows.join('\n');
}());
