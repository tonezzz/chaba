-- PostgreSQL trigger for automatic Wiki → Weaviate sync
-- This creates a NOTIFY event whenever articles are modified

-- Create the notify function
CREATE OR REPLACE FUNCTION notify_article_change()
RETURNS TRIGGER AS $$
DECLARE
    payload JSON;
BEGIN
    -- Build payload based on operation type
    IF TG_OP = 'INSERT' THEN
        payload = json_build_object(
            'op', 'INSERT',
            'id', NEW.id,
            'title', NEW.title,
            'tags', NEW.tags,
            'updated_at', NEW.updated_at
        );
    ELSIF TG_OP = 'UPDATE' THEN
        payload = json_build_object(
            'op', 'UPDATE',
            'id', NEW.id,
            'title', NEW.title,
            'tags', NEW.tags,
            'updated_at', NEW.updated_at,
            'old_title', OLD.title
        );
    ELSIF TG_OP = 'DELETE' THEN
        payload = json_build_object(
            'op', 'DELETE',
            'id', OLD.id,
            'title', OLD.title
        );
    END IF;
    
    -- Send notification on 'wiki_article_change' channel
    PERFORM pg_notify('wiki_article_change', payload::text);
    
    -- Return appropriate row for the operation
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    ELSE
        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Drop existing trigger if it exists
DROP TRIGGER IF EXISTS article_change_trigger ON articles;

-- Create the trigger
CREATE TRIGGER article_change_trigger
    AFTER INSERT OR UPDATE OR DELETE ON articles
    FOR EACH ROW
    EXECUTE FUNCTION notify_article_change();

-- Grant permissions
ALTER FUNCTION notify_article_change() OWNER TO chaba;

-- Verify trigger creation
SELECT 
    tgname AS trigger_name,
    tgrelid::regclass AS table_name,
    CASE tgtype & 2 WHEN 2 THEN 'BEFORE' ELSE 'AFTER' END AS timing,
    CASE 
        WHEN tgtype & 4 = 4 THEN 'INSERT'
        WHEN tgtype & 8 = 8 THEN 'DELETE'
        WHEN tgtype & 16 = 16 THEN 'UPDATE'
        ELSE 'OTHER'
    END AS event
FROM pg_trigger
WHERE tgrelid = 'articles'::regclass
AND NOT tgisinternal;
