"""PDF-only rounding must preserve clipping, strokes and small geometry."""
import pikepdf
import pytest

from pdf2ai.pdf_path_defaults import align_pdf_fill_paths, round_pdf_coordinate
from pdf2ai.vector import read_drawing


def make_page(content, size=(100,100)):
    pdf=pikepdf.new()
    page=pdf.add_blank_page(page_size=size)
    page.Contents=pdf.make_stream(content)
    return pdf,page


def instructions(page):
    return [(str(op),tuple(str(v) for v in args)) for args,op in pikepdf.parse_content_stream(page)]


def test_background_is_trimmed_to_fractional_artboard():
    pdf,page=make_page(b'0 0 0 1 k -10 -10 180 110 re f*',(162.99213,85.03937))
    assert align_pdf_fill_paths(page)==1
    paths=read_drawing(page).paths
    assert paths[0].even_odd
    assert paths[0].paths[0].commands==[
        ('m',(0.,0.)),('L',(162.992,0.)),('L',(162.992,85.039)),('L',(0.,85.039))]


def test_transformed_curve_displacement_stays_below_one_thousandth_pt():
    pdf,page=make_page(b'q 2 .3 -.4 .7 12.345678 9.876543 cm '
                       b'0 0 0 1 k 1.234567 2.345678 m '
                       b'2.111111 4.222222 5.333333 6.444444 8.555555 9.666666 c '
                       b'9.234567 2.345678 l h f Q')
    before=read_drawing(page).paths[0].paths[0].commands
    assert align_pdf_fill_paths(page)==1
    after=read_drawing(page).paths[0].paths[0].commands
    assert [op for op,_ in before]==[op for op,_ in after]
    for (_,a),(_,b) in zip(before,after):
        assert b==pytest.approx(a,abs=.0008)


def test_thin_subpaths_are_not_collapsed():
    pdf,page=make_page(b'0 0 0 1 k 10.123456 20.123456 .0002 5 re f')
    assert align_pdf_fill_paths(page)==1
    path=read_drawing(page).paths[0].paths[0]
    xs=[values[0] for _,values in path.commands]
    assert max(xs)-min(xs)==pytest.approx(.0002,abs=1e-10)


def test_interleaved_style_preserves_the_entire_unfinished_path():
    pdf,page=make_page(b'10.123456 20.123456 m 30.123456 20.123456 l '
                       b'0 0 0 1 k 40.123456 50.123456 m 60.123456 70.123456 l f')
    original=page.Contents.read_bytes()
    assert align_pdf_fill_paths(page)==0
    assert page.Contents.read_bytes()==original


def test_clipping_and_stroke_geometry_remain_exact():
    content=(b'0 0 0 1 k 1.123456 2.234567 90.123456 80.234567 re W n '
             b'0 0 0 1 K 1.234567 w 3.456789 4.567891 m 9.876543 8.765432 l S')
    pdf,page=make_page(content)
    original=page.Contents.read_bytes()
    assert align_pdf_fill_paths(page)==0
    assert page.Contents.read_bytes()==original


def test_normalizing_one_page_does_not_change_shared_contents():
    pdf,page=make_page(b'0 0 0 1 k 1.123456 2.234567 30.123456 40.234567 re f')
    second=pdf.add_blank_page(page_size=(100,100));second.Contents=page.Contents
    original=second.Contents.read_bytes()
    assert align_pdf_fill_paths(page)==1
    assert second.Contents.read_bytes()==original
    assert page.Contents.objgen!=second.Contents.objgen


@pytest.mark.parametrize('setting,value',[('/Rotate',90),('/UserUnit',2)])
def test_page_transforms_keep_original_representation(setting,value):
    pdf,page=make_page(b'0 0 0 1 k 1.123456 2.234567 30.123456 40.234567 re f')
    page.obj[setting]=value
    original=page.Contents.read_bytes()
    assert align_pdf_fill_paths(page)==0
    assert page.Contents.read_bytes()==original


def test_extreme_transform_keeps_original_representation():
    pdf,page=make_page(b'q 1000 0 0 1000 0 0 cm 0 0 0 1 k .01 .01 .02 .02 re f Q')
    original=page.Contents.read_bytes()
    assert align_pdf_fill_paths(page)==0
    assert page.Contents.read_bytes()==original


def test_exact_grid_paths_do_not_add_normalization_wrappers():
    pdf,page=make_page(b'0 0 0 1 k 10 20 30 40 re f')
    original=page.Contents.read_bytes()
    assert align_pdf_fill_paths(page)==0
    assert page.Contents.read_bytes()==original


def test_separate_open_subpaths_are_not_mistaken_for_a_background():
    pdf,page=make_page(b'0 0 0 1 k -10 -10 m 110 -10 l 110 110 m -10 110 l f')
    original=page.Contents.read_bytes()
    assert align_pdf_fill_paths(page)==0
    assert page.Contents.read_bytes()==original


@pytest.mark.parametrize('value,places,expected',[
    (1.25,1,1.3),(-1.25,1,-1.3),(2.1865,3,2.187),(-2.1865,3,-2.187),
    (.0005,3,.001),(-.0005,3,-.001),(12,3,12),(1.2344,3,1.234),
])
def test_pdf_decimal_ties_round_away_from_zero(value,places,expected):
    assert round_pdf_coordinate(value,places)==expected


def test_gap_between_distinct_subpaths_is_not_closed_by_rounding():
    pdf,page=make_page(b'0 0 0 1 k 0 0 10 10 re 10.0002 0 10 10 re f')
    original=page.Contents.read_bytes()
    assert align_pdf_fill_paths(page)==0
    assert page.Contents.read_bytes()==original
    paths=read_drawing(page).paths[0].paths
    gap=paths[1].commands[0][1][0]-paths[0].commands[1][1][0]
    assert gap==pytest.approx(.0002,abs=1e-12)


def test_nonadjacent_distinct_anchors_are_not_merged_by_rounding():
    pdf,page=make_page(b'0 0 0 1 k 0 0 m 10 0 l 10 10 l 0 10 l 0 20 l '
                       b'10.0002 20 l 10.0002 10 l 20 10 l 20 0 l 0 0 l h f')
    original=page.Contents.read_bytes()
    assert align_pdf_fill_paths(page)==0
    assert page.Contents.read_bytes()==original


def test_shared_anchors_remain_joined_when_another_gap_requires_protection():
    # The first contour shares an exact edge with the third contour. The
    # second/third contours have a small gap. Protecting only the third one
    # would break its exact join to the first, depending on contour order.
    pdf,page=make_page(b'0 0 0 1 k 35.12345 0 m 35.12345 10 l '
                       b'20.0002 10 l 20.0002 0 l h '
                       b'0 0 10 10 re 10.0002 0 10 10 re f')
    align_pdf_fill_paths(page)
    paths=read_drawing(page).paths[0].paths
    first=[v for op,v in paths[0].commands]
    third=[v for op,v in paths[2].commands]
    assert first[2]==pytest.approx(third[2],abs=1e-12)
    assert first[3]==pytest.approx(third[1],abs=1e-12)
    gap=paths[2].commands[0][1][0]-paths[1].commands[1][1][0]
    assert gap==pytest.approx(.0002,abs=1e-12)


@pytest.mark.parametrize('paint',[b'f',b'f*'])
def test_backtracking_zero_area_path_is_not_expanded_to_page(paint):
    # Four axis-aligned edges and a page-sized bounding box do not imply a
    # rectangle: these two retraced lines enclose no area.
    content=b'0 0 0 1 k -10 -10 m 110 -10 l -10 -10 l -10 110 l h '+paint
    pdf,page=make_page(content)
    original=page.Contents.read_bytes()
    assert align_pdf_fill_paths(page)==0
    assert page.Contents.read_bytes()==original
