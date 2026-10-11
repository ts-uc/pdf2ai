#target illustrator
(function () {
    var folder = new Folder(new File($.fileName).parent.parent + '/output/multiboard-check');
    var rows = [];
    var files = folder.getFiles('*.ai');
    for (var i=0; i<files.length; i++) {
        var d = app.open(files[i]);
        rows.push('FILE=' + files[i].name + ' TYPE=' + typeof files[i].name + ' EQUAL=' + (files[i].name == 'pages-combined.ai') + ' LENGTH=' + d.artboards.length + ' TYPE=' + typeof d.artboards.length);
        for(var j=0;j<d.artboards.length;j++) rows.push('NAME=' + d.artboards[j].name + ' TYPE=' + typeof d.artboards[j].name);
        d.close(SaveOptions.DONOTSAVECHANGES);
    }
    return rows.join('\n');
}());
