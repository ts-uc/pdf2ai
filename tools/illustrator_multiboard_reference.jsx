#target illustrator
(function () {
    var folder = new Folder(new File($.fileName).parent.parent + '/output/multiboard-check');
    if (!folder.exists) folder.create();
    var d = app.documents.add(DocumentColorSpace.CMYK, 100, 100);
    try {
        d.artboards[0].name = 'ページ 2';
        d.artboards.add([120, 100, 220, 0]).name = 'ページ 4';
        d.pathItems.rectangle(90, 10, 50, 50);
        d.pathItems.rectangle(90, 130, 30, 30);
        var options = new IllustratorSaveOptions(); options.pdfCompatible = true;
        options.compatibility = Compatibility.ILLUSTRATOR24;
        d.saveAs(new File(folder + '/reference.ai'), options);
    } finally { d.close(SaveOptions.DONOTSAVECHANGES); }
}());
