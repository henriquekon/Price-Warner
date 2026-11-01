"""Book format choices must map to independent ASINs."""
from engine.addons.amazon_parser import extract_amazon_variants, parse_amazon_product
from bs4 import BeautifulSoup

HTML = '''
<html><title>Plato Complete Works</title><div id="productTitle">Plato Complete Works</div>
<div id="formats"><div id="tmmSwatches">
<div class="swatchElement unselected"><a href="/Plato-Complete-Works-English-ebook/dp/B00OZ4NMHU/ref=tmm" aria-checked="false"><span class="slot-title">Kindle</span><span class="slot-price"><span aria-label="R$ 242,18"></span></span></a></div>
<div class="swatchElement selected"><a href="javascript:void(0)" aria-checked="true"><span class="slot-title">Capa dura</span><span class="slot-price"><span aria-label="R$ 374,66"></span></span></a></div>
</div></div>
<div id="buybox"><div class="a-accordion-active"><span class="apex-pricetopay-value"><span class="a-offscreen">R$ 374,66</span></span></div></div>
</html>
'''
URL = 'https://www.amazon.com.br/dp/0872203492'


def test_book_format_choices_are_distinct_products():
    product = parse_amazon_product(HTML, URL)
    assert product.status == 'ok'
    assert product.price == '374.66'
    assert len(product.variants) == 2
    kindle, hardcover = product.variants
    assert kindle['asin'] == 'B00OZ4NMHU'
    assert kindle['url'] == 'https://www.amazon.com.br/dp/B00OZ4NMHU'
    assert kindle['selected'] is False
    assert hardcover['asin'] == '0872203492'
    assert hardcover['selected'] is True


def test_no_variants_for_simple_product():
    assert extract_amazon_variants(BeautifulSoup('<html></html>', 'html.parser'), 'B08KK3FB5G') == ()
