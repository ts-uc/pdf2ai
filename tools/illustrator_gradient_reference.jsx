#target illustrator
(function () {
    var folder=new Folder(new File($.fileName).parent.parent+'/output/fidelity-check');
    var d=app.documents.add(DocumentColorSpace.RGB,400,240);
    try {
        var g=d.gradients.add();g.name='Reference gradient';g.type=GradientType.LINEAR;
        var blue=new RGBColor();blue.red=0;blue.green=0;blue.blue=255;
        var red=new RGBColor();red.red=255;red.green=0;red.blue=0;
        g.gradientStops[0].color=blue;g.gradientStops[0].rampPoint=0;
        g.gradientStops[1].color=red;g.gradientStops[1].rampPoint=100;
        var fill=new GradientColor();fill.gradient=g;fill.origin=[200,-50];fill.length=320;
        fill.matrix=app.getRotationMatrix(90);
        var p=d.pathItems.rectangle(160,30,320,130);p.stroked=false;p.fillColor=fill;
        p.rotate(90,false,false,true,false,Transformation.CENTER);
        var options=new IllustratorSaveOptions();options.pdfCompatible=true;
        options.compatibility=Compatibility.ILLUSTRATOR24;
        d.saveAs(new File(folder+'/gradient-reference.ai'),options);
    } finally {d.close(SaveOptions.DONOTSAVECHANGES);}
}());
