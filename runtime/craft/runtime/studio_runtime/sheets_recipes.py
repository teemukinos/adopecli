"""Reusable budget configuration, with user content kept only in owned projects."""
import copy
from . import sheets_source as source
from .sheets_source import require

RECIPE = 'production_budget'


def catalog():
    return [{'id':RECIPE, 'version':1, 'editable':True, 'shares_user_content':False,
             'required':['title','currency','tax_rate','items'], 'maximum_items':100,
             'outputs':['native workbook','CSV values','HTML preview']}]


def validate(params):
    source.fields(params, ('recipe','version','title','currency','tax_rate','items'), 'budget recipe')
    require(params['recipe']==RECIPE and type(params['version']) is int and params['version']==1, 'budget recipe/version unsupported')
    source.text(params['title'],512,'budget title');source.text(params['currency'],12,'currency label')
    source.number(params['tax_rate'],'tax rate');require(0 <= params['tax_rate'] <= 1,'tax rate must be between zero and one')
    require(type(params['items']) is list and 1 <= len(params['items']) <= 100,'budget needs 1..100 items')
    for item in params['items']:
        source.fields(item,('name','quantity','unit_price'),'budget item');source.text(item['name'],512,'item name')
        for key in ('quantity','unit_price'):
            source.number(item[key],key);require(0 <= item[key] <= 1e9,key+' exceeds recipe bounds')


def compile(params):
    validate(params);model=source.baseline();model['sheets'][0]['name']='Budget'
    rates=copy.deepcopy(model['sheets'][0]);rates['name']='Rates';model['sheets'].append(rates)
    changes=[]
    def put(sheet,cell,**values):changes.append({'sheet':sheet,'cell':cell,**values})
    put(0,'A1',value=params['title'],format={'bold':True})
    for col,label in zip('ABCD',('Item','Quantity','Unit price ('+params['currency']+')','Total ('+params['currency']+')')):
        put(0,col+'2',value=label,format={'bold':True})
    put(1,'A1',value='Rate');put(1,'B1',value='Value');put(1,'A2',value='Tax');put(1,'B2',value=params['tax_rate'],format={'number_format':'0.00%'})
    for row,item in enumerate(params['items'],3):
        put(0,'A'+str(row),value=item['name']);put(0,'B'+str(row),value=item['quantity'])
        put(0,'C'+str(row),value=item['unit_price'],format={'number_format':'#,##0.00'})
        put(0,'D'+str(row),formula=f'ROUND(B{row}*C{row},2)',format={'number_format':'#,##0.00'})
    last=len(params['items'])+2;subtotal=last+2;tax=last+3;total=last+4
    for row,label,formula in ((subtotal,'Subtotal',f'SUM(D3:D{last})'),(tax,'Tax',f'ROUND(D{subtotal}*Rates!B2,2)'),(total,'Total',f'D{subtotal}+D{tax}')):
        put(0,'C'+str(row),value=label,format={'bold':True});put(0,'D'+str(row),formula=formula,format={'bold':True,'number_format':'#,##0.00'})
    return {'source':source.encoded(model),'operation':{'kind':'cells.edit','edits':source.edits(changes)},
            'recipe':{'id':RECIPE,'version':1,'total_cell':'D'+str(total),'defaults_sha256':source.BASE_SHA256,'shares_user_content':False}}
