#target illustrator
(function () {
    var root = new File($.fileName).parent.parent;
    var input = new File(root + '/output/toyo-book-input.json');
    input.encoding = 'UTF-8';
    if (!input.open('r')) throw new Error('Cannot open TOYO book input');
    var colors = eval('(' + input.read() + ')'); input.close();
    var rows = [], count = 0;
    for (var name in colors) {
        if (!colors.hasOwnProperty(name)) continue;
        var lab = colors[name].lab;
        var cmyk = app.convertSampleColor(ImageColorSpace.LAB, lab, ImageColorSpace.CMYK, ColorConvertPurpose.defaultpurpose);
        for (var i = 0; i < cmyk.length; i++) cmyk[i] /= 100;
        rows.push('  "' + name.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '": {"lab":[' + lab.join(',') + '],"cmyk":[' + cmyk.join(',') + ']}');
        count++;
    }
    var output = new File(root + '/src/pdf2ai/data/toyo_lab.json');
    output.encoding = 'UTF-8';
    if (!output.open('w')) throw new Error('Cannot write TOYO data');
    output.write('{\n' + rows.join(',\n') + '\n}\n'); output.close();
    return count + ' TOYO Lab swatches exported with CMYK preview values';
}());
